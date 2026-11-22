# Worker de fila (sem porta: so consome o Redis).
# Contexto de build = RAIZ do repositorio, pois usa o pacote comum/:
#   docker build -f worker/Dockerfile -t plataforma-worker .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MODELO_CAMINHO=/app/modelo/modelo.joblib

WORKDIR /app

COPY worker/requirements.txt .
RUN pip install -r requirements.txt

COPY comum/ comum/
RUN mkdir -p modelo && python -c "from comum.modelo import carregar_modelo; carregar_modelo()"

COPY worker/worker.py .

RUN useradd --create-home --uid 10001 app
USER app

# Saudavel = consegue falar com o Redis da fila.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "from comum import fila; fila.cliente().ping()"

# Forma exec: o python e o PID 1 e trata o SIGTERM (encerramento limpo).
CMD ["opentelemetry-instrument", "python", "worker.py"]
