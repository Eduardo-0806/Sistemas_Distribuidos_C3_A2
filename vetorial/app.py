"""
Servico de ARMAZENAMENTO VETORIAL (reaproveitado do C2.A2).

No C2.A2 eram dois servicos: a ingestao guardava o indice e a recuperacao
baixava o indice INTEIRO pela rede a cada busca. Aqui o armazenamento e dono
dos dados: indexa, persiste e busca no mesmo lugar - a consulta trafega so a
pergunta e os top_k resultados.

Rotas (chamadas SOMENTE pelo gateway):
    GET  /saude        estado e total de documentos
    POST /documentos   indexa uma lista de {"texto", "origem"} -> 201
    POST /buscar       {"pergunta", "top_k"} -> trechos mais parecidos

Persistencia: o indice (texto, origem e vetor de cada documento) e gravado
num arquivo JSON de forma ATOMICA (escreve num temporario e renomeia), num
volume do Docker - sobrevive a restart e a recriacao do container.
Na primeira subida, com o indice vazio, indexa os .txt de DOCUMENTOS_INICIAIS.

Configuracao (variaveis de ambiente):
    ARQUIVO_INDICE      onde o indice e persistido (padrao dados/indice.json)
    DOCUMENTOS_INICIAIS pasta com .txt para popular o indice vazio
                        (padrao: documentos/ ao lado deste arquivo; "" desliga)

Rodar local (dentro de vetorial/): uvicorn app:app --port 8002
"""
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import Body, FastAPI, Request, status
from pydantic import BaseModel, Field

from embeddings import Vetorizador

ARQUIVO_INDICE = Path(os.getenv("ARQUIVO_INDICE", "dados/indice.json"))
DOCUMENTOS_INICIAIS = os.getenv(
    "DOCUMENTOS_INICIAIS", str(Path(__file__).parent / "documentos"))

vetorizador = Vetorizador()
INDICE: list[dict] = []
# Protege INDICE, vetorizador e arquivo: escrita e busca nao se misturam.
_trava = threading.Lock()


class Documento(BaseModel):
    texto: str = Field(min_length=1, max_length=20_000)
    origem: str = Field("desconhecida", max_length=200)


class Consulta(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(3, ge=1, le=20)


# --------------------------------------------------------------------------
# Indice
# --------------------------------------------------------------------------
def _revetorizar() -> None:
    """TF-IDF: o vocabulario depende de TODOS os textos, entao cada inclusao
    reajusta o vocabulario e recalcula os vetores (custo O(n) por escrita)."""
    if not INDICE:
        return
    vetorizador.ajustar([i["texto"] for i in INDICE])
    for item in INDICE:
        item["vetor"] = vetorizador.vetorizar(item["texto"])


def salvar_indice() -> None:
    """Escrita atomica: uma queda no meio nao corrompe o arquivo anterior."""
    ARQUIVO_INDICE.parent.mkdir(parents=True, exist_ok=True)
    temporario = ARQUIVO_INDICE.with_suffix(".tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(INDICE, f, ensure_ascii=False)
    os.replace(temporario, ARQUIVO_INDICE)


def carregar_indice() -> None:
    if ARQUIVO_INDICE.exists():
        with open(ARQUIVO_INDICE, encoding="utf-8") as f:
            INDICE.extend(json.load(f))
        _revetorizar()  # refaz o vocabulario para vetorizar novas perguntas
        print(f"[vetorial] indice carregado: {len(INDICE)} documentos")
        return
    pasta = Path(DOCUMENTOS_INICIAIS) if DOCUMENTOS_INICIAIS else None
    if pasta and pasta.is_dir():
        for arq in sorted(pasta.glob("*.txt")):
            INDICE.append({"texto": arq.read_text(encoding="utf-8").strip(),
                           "origem": arq.stem})
        if INDICE:
            _revetorizar()
            salvar_indice()
            print(f"[vetorial] indice inicial: {len(INDICE)} documentos")


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    with _trava:
        carregar_indice()
    yield


app = FastAPI(title="Armazenamento Vetorial - C3.A2", lifespan=ciclo_de_vida)


@app.middleware("http")
async def registrar(request: Request, call_next):
    # Log sem conteudo: nunca imprime textos nem perguntas.
    inicio = time.time()
    resposta = await call_next(request)
    ms = (time.time() - inicio) * 1000
    print(f"[vetorial] {request.method} {request.url.path} "
          f"-> {resposta.status_code} ({ms:.1f}ms)")
    return resposta


# --------------------------------------------------------------------------
# Rotas
# --------------------------------------------------------------------------
@app.get("/saude")
def saude():
    return {"status": "ok", "documentos": len(INDICE)}


@app.post("/documentos", status_code=status.HTTP_201_CREATED)
def indexar(docs: Annotated[list[Documento],
                             Body(min_length=1, max_length=100)]):
    with _trava:
        for d in docs:
            INDICE.append({"texto": d.texto, "origem": d.origem})
        _revetorizar()
        salvar_indice()
        return {"indexados": len(docs), "total": len(INDICE)}


@app.post("/buscar")
def buscar(consulta: Consulta):
    """Top_k documentos por similaridade do cosseno com a pergunta."""
    with _trava:
        if not INDICE:
            return {"pergunta": consulta.pergunta, "resultados": []}
        q = np.array(vetorizador.vetorizar(consulta.pergunta))
        matriz = np.array([i["vetor"] for i in INDICE])
        normas = np.linalg.norm(matriz, axis=1) * np.linalg.norm(q)
        scores = np.divide(matriz @ q, normas, out=np.zeros(len(INDICE)),
                           where=normas > 0)
        ordem = np.argsort(-scores)[:consulta.top_k]
        # score 0 = nenhum termo em comum com a pergunta: nao e relevante.
        resultados = [{"texto": INDICE[i]["texto"],
                       "origem": INDICE[i]["origem"],
                       "score": round(float(scores[i]), 4)}
                      for i in ordem if scores[i] > 0]
    return {"pergunta": consulta.pergunta, "resultados": resultados}
