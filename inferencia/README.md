# Serviço de inferência

Reaproveitado do C1.A2. Recebe pedidos **somente do gateway** (porta 8001, não
exposta para fora no compose).

| Rota | O que faz |
|---|---|
| `GET /saude` | estado do serviço, do modelo e da conexão com o Redis |
| `POST /predict` | **assíncrono**: põe a tarefa na fila do Redis e devolve `{"id"}` com 202 |
| `GET /resultado/{id}` | `na_fila`, `pronto` (com o resultado) ou `erro`; 404 se não existe/expirou |
| `POST /predict-sync` | **síncrono**: roda o modelo na hora (para comparar latência) |

O modelo e a fila ficam em [`../comum/`](../comum), compartilhados com o worker.

## Container

O contexto de build é a **raiz do repositório** (por causa de `comum/`):

```bash
docker build -f inferencia/Dockerfile -t plataforma-inferencia .
```

- o modelo é treinado **no build**, então o container já sobe pronto;
- roda como usuário sem privilégios e tem `HEALTHCHECK` em `/saude`;
- configuração por ambiente: `REDIS_URL`, `RESULTADO_TTL_S`, `PORT`.
