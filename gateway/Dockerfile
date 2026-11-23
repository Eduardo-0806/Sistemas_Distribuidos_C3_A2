# API Gateway (porta publica, 8000 por padrao).
# Contexto de build = pasta gateway/:
#   docker build -t plataforma-gateway gateway
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py limitador.py resiliencia.py ./

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/saude', timeout=2)"

# HOST e PORT vem do ambiente. Local: 0.0.0.0 (IPv4). No Railway use HOST=::
# (rede privada *.railway.internal; no Linux "::" aceita IPv4 e IPv6).
# --no-access-log: o log de acesso do uvicorn grava o IP do cliente (dado
# pessoal, LGPD). O middleware do servico ja loga metodo, rota, status e tempo.
CMD ["sh", "-c", "exec opentelemetry-instrument uvicorn app:app --host ${HOST:-0.0.0.0} --port ${PORT} --no-access-log"]
