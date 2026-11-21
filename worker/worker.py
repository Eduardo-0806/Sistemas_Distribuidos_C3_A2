"""
Worker de fila (reaproveitado do C1.A2): consome "tarefas" no Redis, roda o
modelo e grava o resultado para o cliente consultar depois.

Escala horizontalmente: suba N workers e a fila divide a carga entre eles
(BLPOP entrega cada tarefa para UM worker so).

    docker compose up --scale worker=3

Configuracao (variaveis de ambiente):
    REDIS_URL        Redis da fila (padrao redis://localhost:6379/0)
    RESULTADO_TTL_S  quanto tempo o resultado fica guardado (padrao 3600)
    MODELO_CAMINHO   onde fica o modelo treinado (opcional)

Rodar local (da raiz do repo): python -m worker.worker
(Retentativa e fila de descarte: TAREFA 6 - resiliencia.)
"""
import signal
import time

import redis

from comum import fila
from comum.modelo import carregar_modelo

_rodando = True


def _parar(signum, _frame):
    """`docker stop` manda SIGTERM: termina a tarefa atual e sai limpo."""
    global _rodando
    _rodando = False
    print(f"[worker] sinal {signum} recebido, encerrando...")


def processar(modelo, tarefa: dict) -> dict:
    """Roda o modelo e grava o resultado. Devolve o que foi gravado."""
    inicio = time.time()
    try:
        r = modelo.prever(tarefa["texto"])
        r.pop("texto", None)  # LGPD/minimizacao: o cliente ja tem o texto
        r["status"] = "pronto"
        r["tempo_ms"] = round((time.time() - inicio) * 1000, 2)
    except Exception as erro:  # noqa: BLE001
        print(f"[worker] ERRO na tarefa {tarefa['id']}: {type(erro).__name__}")
        r = {"status": "erro", "erro": type(erro).__name__}
    fila.guardar_resultado(tarefa["id"], r)
    return r


def main():
    signal.signal(signal.SIGTERM, _parar)
    signal.signal(signal.SIGINT, _parar)

    print("[worker] carregando modelo...")
    modelo = carregar_modelo()
    print("[worker] pronto. aguardando tarefas")

    while _rodando:
        try:
            tarefa = fila.proxima_tarefa(timeout=2)
        except redis.RedisError as e:
            print(f"[worker] redis indisponivel ({type(e).__name__}); "
                  f"tentando de novo em 2s")
            time.sleep(2)
            continue
        if tarefa is None:
            continue
        r = processar(modelo, tarefa)
        # Log sem dados pessoais: so id, status e tempo.
        print(f"[worker] tarefa {tarefa['id']} -> {r['status']} "
              f"({r.get('tempo_ms', '-')}ms)")

    print("[worker] encerrado")


if __name__ == "__main__":
    main()
