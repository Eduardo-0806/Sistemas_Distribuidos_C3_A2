"""
Fila de tarefas no Redis - contrato COMPARTILHADO entre inferencia e worker.

Fluxo (Aula 8): quem pede nao espera.
    inferencia  RPUSH  "tarefas"            {"id", "texto"}
    worker      BLPOP  "tarefas"            -> roda o modelo
    worker      SET    "resultado:<id>"     {"status": "pronto", ...}
    cliente     GET    "resultado:<id>"     (via gateway -> inferencia)

LGPD: todo resultado expira sozinho apos RESULTADO_TTL_S segundos
(padrao 1h) - nada fica guardado indefinidamente.
"""
import json
import os
import uuid

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RESULTADO_TTL_S = int(os.getenv("RESULTADO_TTL_S", "3600"))
FILA_TAREFAS = "tarefas"
PREFIXO_RESULTADO = "resultado:"

_cliente = None


def cliente() -> "redis.Redis":
    global _cliente
    if _cliente is None:
        _cliente = redis.from_url(REDIS_URL, socket_timeout=10,
                                  decode_responses=True)
    return _cliente


def enfileirar(texto: str) -> str:
    """Coloca uma tarefa na fila e devolve o id para consulta posterior."""
    tarefa_id = str(uuid.uuid4())
    # Grava o status ANTES de enfileirar: assim o worker nunca termina uma
    # tarefa cujo status "na_fila" ainda vai ser escrito (e sobrescrito) depois.
    cliente().set(PREFIXO_RESULTADO + tarefa_id,
                  json.dumps({"status": "na_fila"}), ex=RESULTADO_TTL_S)
    cliente().rpush(FILA_TAREFAS, json.dumps({"id": tarefa_id, "texto": texto}))
    return tarefa_id


def proxima_tarefa(timeout: int = 5):
    """Bloqueia ate chegar tarefa (ou timeout). Usado pelo worker."""
    item = cliente().blpop(FILA_TAREFAS, timeout=timeout)
    if item is None:
        return None
    return json.loads(item[1])


def guardar_resultado(tarefa_id: str, resultado: dict) -> None:
    cliente().set(PREFIXO_RESULTADO + tarefa_id, json.dumps(resultado),
                  ex=RESULTADO_TTL_S)


def buscar_resultado(tarefa_id: str):
    bruto = cliente().get(PREFIXO_RESULTADO + tarefa_id)
    return json.loads(bruto) if bruto else None


def tamanho_fila() -> int:
    return int(cliente().llen(FILA_TAREFAS))
