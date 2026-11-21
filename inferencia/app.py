"""
Servico de inferencia (reaproveitado do C1.A2).

Rotas (chamadas SOMENTE pelo gateway, que faz JWT e rate limit):
    GET  /saude              estado do servico e da conexao com o Redis
    POST /predict            ASSINCRONO: enfileira e devolve {"id"} com 202
    GET  /resultado/{id}     status/resultado da tarefa (404 se nao existir)
    POST /predict-sync       SINCRONO: roda o modelo na hora (comparacao de
                             latencia sync x fila no relatorio de trade-offs)

Configuracao (variaveis de ambiente):
    REDIS_URL        Redis da fila (padrao redis://localhost:6379/0)
    RESULTADO_TTL_S  quanto tempo o resultado fica guardado (padrao 3600)
    MODELO_CAMINHO   onde fica o modelo treinado (opcional)

Rodar local (da raiz do repo): uvicorn inferencia.app:app --port 8001
"""
import time
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from comum import fila
from comum.modelo import carregar_modelo

modelo = None


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    """Carrega o modelo UMA vez, na subida - nao a cada requisicao (Aula 6)."""
    global modelo
    inicio = time.time()
    modelo = carregar_modelo()
    print(f"[inferencia] modelo carregado em {time.time() - inicio:.3f}s")
    yield


app = FastAPI(title="Servico de Inferencia - C3.A2", lifespan=ciclo_de_vida)


class Entrada(BaseModel):
    texto: str


def _validar(entrada: Entrada) -> None:
    if not entrada.texto.strip():
        raise HTTPException(status_code=400, detail="texto vazio")


def _redis_indisponivel(e: Exception) -> HTTPException:
    return HTTPException(status_code=503,
                         detail=f"fila indisponivel ({type(e).__name__})")


@app.middleware("http")
async def registrar(request: Request, call_next):
    # Log sem dados pessoais: nunca imprime o texto enviado.
    inicio = time.time()
    resposta = await call_next(request)
    ms = (time.time() - inicio) * 1000
    print(f"[inferencia] {request.method} {request.url.path} "
          f"-> {resposta.status_code} ({ms:.1f}ms)")
    return resposta


@app.get("/saude")
def saude():
    try:
        redis_ok = bool(fila.cliente().ping())
    except redis.RedisError:
        redis_ok = False
    return {"status": "ok", "modelo_carregado": modelo is not None,
            "redis": redis_ok}


@app.post("/predict", status_code=status.HTTP_202_ACCEPTED)
def predict(entrada: Entrada):
    """Enfileira a tarefa e devolve o id SEM esperar a inferencia."""
    _validar(entrada)
    try:
        return {"id": fila.enfileirar(entrada.texto), "status": "na_fila"}
    except redis.RedisError as e:
        raise _redis_indisponivel(e)


@app.get("/resultado/{tarefa_id}")
def resultado(tarefa_id: str):
    try:
        r = fila.buscar_resultado(tarefa_id)
    except redis.RedisError as e:
        raise _redis_indisponivel(e)
    if r is None:
        raise HTTPException(status_code=404,
                            detail="tarefa nao encontrada (ou expirada)")
    return {"id": tarefa_id, **r}


@app.post("/predict-sync")
def predict_sync(entrada: Entrada):
    """Inferencia SINCRONA: o cliente espera a resposta."""
    _validar(entrada)
    inicio = time.time()
    r = modelo.prever(entrada.texto)
    r["tempo_ms"] = round((time.time() - inicio) * 1000, 2)
    return r
