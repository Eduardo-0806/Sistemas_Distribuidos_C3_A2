"""Timeout, retentativas com backoff e circuit breaker para chamadas HTTP."""
import threading
import time


class Disjuntor:
    """Disjuntor thread-safe: fechado, aberto e meia-volta com uma sondagem."""

    def __init__(self, limite_falhas: int, descanso_s: float):
        self.limite_falhas = limite_falhas
        self.descanso_s = descanso_s
        self._falhas = 0
        self._aberto_ate = 0.0
        self._meia_volta_em_uso = False
        self._lock = threading.Lock()

    def permitir(self) -> bool:
        agora = time.monotonic()
        with self._lock:
            if self._aberto_ate == 0:
                return True
            if agora < self._aberto_ate:
                return False
            if self._meia_volta_em_uso:
                return False
            self._meia_volta_em_uso = True
            return True

    def sucesso(self) -> None:
        with self._lock:
            self._falhas = 0
            self._aberto_ate = 0.0
            self._meia_volta_em_uso = False

    def falha(self) -> None:
        agora = time.monotonic()
        with self._lock:
            estava_em_meia_volta = self._meia_volta_em_uso
            self._meia_volta_em_uso = False
            self._falhas += 1
            if estava_em_meia_volta or self._falhas >= self.limite_falhas:
                self._aberto_ate = agora + self.descanso_s


class Retentativas:
    """Calcula espera exponencial limitada entre chamadas que podem ser repetidas."""

    def __init__(self, max_tentativas: int, espera_inicial_s: float,
                 espera_maxima_s: float):
        self.max_tentativas = max_tentativas
        self.espera_inicial_s = espera_inicial_s
        self.espera_maxima_s = espera_maxima_s

    def esperar(self, tentativa: int) -> None:
        espera = min(self.espera_inicial_s * (2 ** (tentativa - 1)),
                     self.espera_maxima_s)
        time.sleep(espera)
