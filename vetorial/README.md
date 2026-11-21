# Armazenamento vetorial

Reaproveitado do C2.A2 (persistência do índice + busca por similaridade).
Recebe pedidos **somente do gateway** (porta 8002, não exposta no compose).

| Rota | O que faz |
|---|---|
| `GET /saude` | estado e total de documentos |
| `POST /documentos` | indexa uma lista de `{"texto", "origem"}` (1 a 100 por vez) → `201` |
| `POST /buscar` | `{"pergunta", "top_k"}` (1 a 20) → documentos mais parecidos, com `score` |

## Decisões

- **Um serviço só, dono dos dados.** No C2.A2 a recuperação baixava o índice
  inteiro da ingestão a cada busca; aqui indexação e busca ficam juntas e a rede
  carrega só a pergunta e os `top_k` resultados.
- **Persistência atômica** em `/dados/indice.json` (volume `vetorial-dados`):
  grava num temporário e renomeia, então uma queda no meio não corrompe o índice.
- **Base inicial:** com o índice vazio, indexa os `.txt` de `documentos/`.
- **Vetorização TF-IDF** (offline, sem download). Como o vocabulário depende de
  todos os textos, cada inclusão recalcula os vetores: barato para centenas de
  documentos, mas cresce com a base (trade-off documentado no relatório).
- **Instância única:** o índice é um arquivo local, então escalar este serviço
  exigiria um banco vetorial compartilhado. Ver relatório de trade-offs (CAP).

## Container

```bash
docker build -t plataforma-vetorial vetorial
```
