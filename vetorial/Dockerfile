# Armazenamento vetorial (REST, porta 8002).
# Contexto de build = pasta vetorial/:
#   docker build -t plataforma-vetorial vetorial
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ARQUIVO_INDICE=/dados/indice.json \
    PORT=8002

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY embeddings.py app.py ./
COPY documentos/ documentos/

# /dados e o ponto de montagem do volume: precisa pertencer ao usuario do
# container, senao o indice nao pode ser gravado.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /dados && chown app:app /dados
USER app
# Sem instrucao VOLUME: o Railway rejeita (usa Railway Volumes). O volume
# e declarado no docker-compose.yml (local) e anexado em /dados no Railway.

EXPOSE 8002
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/saude', timeout=2)"

# HOST e PORT vem do ambiente. Local: 0.0.0.0 (IPv4). No Railway use HOST=::
# (rede privada *.railway.internal; no Linux "::" aceita IPv4 e IPv6).
CMD ["sh", "-c", "exec opentelemetry-instrument uvicorn app:app --host ${HOST:-0.0.0.0} --port ${PORT}"]
