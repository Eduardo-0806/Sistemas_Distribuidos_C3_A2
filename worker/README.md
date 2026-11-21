# Worker de fila

Reaproveitado do C1.A2. Consome a lista `tarefas` do Redis (`BLPOP`), roda o
modelo e grava `resultado:<id>` com expiração (`RESULTADO_TTL_S`, padrão 1h).

- **Escala horizontal:** cada tarefa vai para **um** worker só, então basta subir
  mais réplicas: `docker compose up --scale worker=3`.
- **Encerramento limpo:** trata o `SIGTERM` do `docker stop`, termina a tarefa
  atual e sai.
- **Logs sem dados pessoais:** registra só id, status e tempo; o texto não vai
  para o resultado salvo (minimização, LGPD).

## Container

O contexto de build é a **raiz do repositório** (por causa de `comum/`):

```bash
docker build -f worker/Dockerfile -t plataforma-worker .
```

`HEALTHCHECK`: o container fica saudável quando consegue falar com o Redis.
