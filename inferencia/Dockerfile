# Servico de inferencia (REST, porta 8001).
# Contexto de build = RAIZ do repositorio, pois usa o pacote comum/:
#   docker build -f inferencia/Dockerfile -t plataforma-inferencia .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MODELO_CAMINHO=/app/modelo/modelo.joblib \
    PORT=8001

WORKDIR /app

# 1) Dependencias primeiro: a camada fica em cache enquanto o
#    requirements.txt nao mudar (rebuild rapido ao editar o codigo).
COPY inferencia/requirements.txt .
RUN pip install -r requirements.txt

# 2) Modelo treinado NO BUILD: o container sobe pronto, sem treinar a cada start.
COPY comum/ comum/
RUN mkdir -p modelo && python -c "from comum.modelo import carregar_modelo; carregar_modelo()"

# 3) Codigo do servico (camada que mais muda fica por ultimo).
COPY inferencia/app.py .

# Nao roda como root.
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/saude', timeout=2)"

# "exec" faz o uvicorn virar o PID 1 e receber o SIGTERM do docker stop.
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
