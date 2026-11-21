"""
Limitador de requisicoes (rate limit) - TAREFA 2.

Algoritmo: JANELA FIXA. O tempo e dividido em janelas de `janela_s` segundos
(ex.: 60s) e cada cliente tem um contador por janela. Passou do limite -> 429
ate a proxima janela comecar.
    + simples, 1 contador por cliente, atomico no Redis (INCR)
    - permite ate 2x o limite numa rajada exatamente na virada da janela

Backends:
    LimitadorRedis       contador COMPARTILHADO entre todas as replicas do
                         gateway (o limite continua correto se houver 3 gateways).
    LimitadorMemoria     contador local do processo (dev/testes e reserva).
    LimitadorComReserva  usa o Redis; se ele falhar, cai para a memoria e
                         para de tentar o Redis por um tempo (evita pagar o
                         tempo-limite em toda requisicao enquanto ele esta fora).
"""
import threading
import time
from typing import NamedTuple, Optional

import redis


class Resultado(NamedTuple):
    permitido: bool
    limite: int
    restantes: int
    reset_em: int  # segundos ate a janela atual terminar


def _resultado(contagem: int, limite: int, janela: int, janela_s: int,
               agora: float) -> Resultado:
    reset_em = max(1, int((janela + 1) * janela_s - agora + 0.999))
    return Resultado(permitido=contagem <= limite, limite=limite,
                     restantes=max(0, limite - contagem), reset_em=reset_em)


class LimitadorMemoria:
    MAX_CHAVES = 10_000  # acima disso, descarta janelas antigas

    def __init__(self):
        self._janelas: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()  # rotas sync rodam em varias threads

    def registrar(self, chave: str, limite: int, janela_s: int,
                  agora: Optional[float] = None) -> Resultado:
        agora = time.time() if agora is None else agora
        janela = int(agora // janela_s)
        with self._lock:
            inicio, contagem = self._janelas.get(chave, (janela, 0))
            if inicio != janela:
                contagem = 0
            contagem += 1
            self._janelas[chave] = (janela, contagem)
            if len(self._janelas) > self.MAX_CHAVES:
                self._janelas = {k: v for k, v in self._janelas.items()
                                 if v[0] == janela}
        return _resultado(contagem, limite, janela, janela_s, agora)


class LimitadorRedis:
    PREFIXO = "ratelimit"

    def __init__(self, cliente: "redis.Redis"):
        self._r = cliente

    def registrar(self, chave: str, limite: int, janela_s: int,
                  agora: Optional[float] = None) -> Resultado:
        agora = time.time() if agora is None else agora
        janela = int(agora // janela_s)
        chave_r = f"{self.PREFIXO}:{chave}:{janela}"
        # MULTI/EXEC: INCR e EXPIRE sao aplicados juntos (atomico).
        # O EXPIRE garante que o Redis apaga sozinho os contadores velhos.
        pipe = self._r.pipeline(transaction=True)
        pipe.incr(chave_r)
        pipe.expire(chave_r, janela_s + 1)
        contagem, _ = pipe.execute()
        return _resultado(int(contagem), limite, janela, janela_s, agora)


class LimitadorComReserva:
    def __init__(self, principal: LimitadorRedis, reserva: LimitadorMemoria,
                 pausa_s: float = 30.0):
        self.principal = principal
        self.reserva = reserva
        self.pausa_s = pausa_s
        self._redis_pausado_ate = 0.0

    def registrar(self, chave: str, limite: int, janela_s: int,
                  agora: Optional[float] = None) -> Resultado:
        if time.monotonic() >= self._redis_pausado_ate:
            try:
                return self.principal.registrar(chave, limite, janela_s, agora)
            except redis.RedisError as e:
                self._redis_pausado_ate = time.monotonic() + self.pausa_s
                print(f"[gateway] redis indisponivel ({type(e).__name__}); "
                      f"rate limit local por {self.pausa_s:.0f}s")
        return self.reserva.registrar(chave, limite, janela_s, agora)


def criar_limitador(redis_url: str = ""):
    """Sem REDIS_URL -> so memoria. Com REDIS_URL -> Redis com reserva local."""
    if not redis_url:
        return LimitadorMemoria()
    cliente = redis.Redis.from_url(redis_url, socket_timeout=0.25,
                                   socket_connect_timeout=0.25)
    return LimitadorComReserva(LimitadorRedis(cliente), LimitadorMemoria())
