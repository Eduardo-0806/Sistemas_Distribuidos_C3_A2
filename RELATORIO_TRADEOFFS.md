# Relatório de trade-offs — CAP, custo e latência

Plataforma de IA como Serviço (C3.A2). Este relatório explica as escolhas de
projeto e o que cada uma custa. Arquitetura e execução estão no [README](README.md).

---

## 1. CAP

O teorema CAP diz que, diante de uma partição de rede, um sistema distribuído
precisa escolher entre **consistência** (C) e **disponibilidade** (A). Cada parte
da plataforma fez uma escolha diferente:

| Componente | Escolha | Por quê |
|---|---|---|
| Fila e resultados (Redis, instância única) | **CP** | Se a inferência não alcança o Redis, o `/predict` responde `503` em vez de aceitar uma tarefa que não conseguiria guardar. Preferimos recusar a perder o pedido do cliente. Com uma instância só, não há réplicas divergindo. |
| Rate limit (Redis com reserva em memória) | **AP** | Se o Redis cai, cada gateway passa a contar em memória local. O serviço continua no ar, mas com N réplicas do gateway o limite efetivo pode chegar a N vezes o configurado enquanto o Redis estiver fora. Aceitamos isso porque o rate limit protege a plataforma, e derrubar todas as requisições por falta do contador seria pior. |
| Armazenamento vetorial (arquivo em volume, instância única) | **CP** | Uma única cópia do índice: toda busca enxerga o último documento indexado. O custo é que, se o serviço cair, a busca fica indisponível (`503` no gateway). Escalar exigiria um banco vetorial compartilhado (ex.: pgvector, Qdrant). |
| Resultado da inferência | **Consistência eventual** visível ao cliente | O `202` volta antes da inferência; o cliente vê `na_fila` até o worker gravar `pronto`. O status `na_fila` é gravado **antes** do `RPUSH`, então o cliente nunca recebe `404` para uma tarefa que acabou de criar. |

**Isolamento de falhas.** Há um circuit breaker por serviço no gateway. Testamos
parando a inferência: as 5 primeiras requisições levaram ~0,6 s cada (3
tentativas com espera de 0,2 s e 0,4 s) e voltaram `503`; a partir da 6ª o
disjuntor abriu e o `503` voltou em ~4 ms, sem chamar o serviço. Durante a falha
o `/buscar` continuou respondendo `200`.

**Semântica de entrega.** O worker retira a tarefa com `BLPOP` antes de
processar: a entrega é **no máximo uma vez**. Se um worker morrer no meio do
processamento, a tarefa se perde e o cliente vê `na_fila` até o TTL expirar.
Escolhemos isso pela simplicidade e porque o modelo roda em poucos milissegundos
(a janela de perda é mínima). A alternativa seria uma fila confiável (`BLMOVE`
para uma lista de "em processamento" e reprocessar o que ficar parado), ao custo
de tarefas possivelmente processadas duas vezes.

**Retentativa x duplicidade.** O gateway só repete chamadas idempotentes
(`GET /resultado`, `POST /buscar`). `POST /predict` e `POST /documentos` não são
repetidos: se a resposta se perder depois de a tarefa ser criada, repetir geraria
uma tarefa ou documento duplicado.

---

## 2. Latência

Medido com o `docker compose` local (2 workers), 200 requisições sequenciais
direto na inferência e 12 pelo gateway (o rate limit é de 30/min por usuário):

| Caminho | p50 | p95 |
|---|---|---|
| Inferência síncrona (`/predict-sync`, sem fila) | 3,1 ms | 5,7 ms |
| Fila: só enfileirar (`/predict` → `202`) | 4,2 ms | 8,3 ms |
| Fila: do envio até o resultado ficar `pronto` | 7,0 ms | 14,7 ms |
| Pelo gateway: `/predict` (JWT + rate limit + fila) | 9,5 ms | 10,4 ms |
| Pelo gateway: `/buscar` | 7,3 ms | 8,7 ms |

O que os números mostram:

- **A fila custa ~4 ms a mais** que a chamada síncrona (7,0 ms contra 3,1 ms no
  p50), por causa das idas ao Redis e do polling do cliente. Com um modelo de
  poucos milissegundos, o modo síncrono seria mais rápido.
- **Mesmo assim mantivemos a fila** porque ela desacopla quem pede de quem
  processa: o gateway responde em ~10 ms independentemente da duração do modelo,
  picos de carga se acumulam na fila em vez de derrubar a API, e a vazão cresce
  só com mais workers (`--scale worker=N`). Se a carga fosse um LLM de vários
  segundos, o modo síncrono prenderia uma thread do gateway por requisição.
- **O gateway soma ~5 ms** (JWT, um `INCR`+`EXPIRE` no Redis para o rate limit e
  um salto HTTP a mais). É o preço de centralizar segurança e resiliência num só
  lugar.
- **Pior caso com serviço travado:** o tempo-limite é de 10 s por tentativa, então
  um `GET /resultado` com a inferência pendurada pode levar até ~30 s antes do
  `503`. Um `SERVICO_TIMEOUT_S` menor reduz isso, mas aumenta o risco de cortar
  requisições lentas legítimas.
- **No deploy público** soma-se o tempo de rede até o Railway e o TLS na borda,
  além da partida a frio quando os serviços estão dormindo (ver custo).

---

## 3. Custo

| Decisão | Economia | Custo/limitação |
|---|---|---|
| Railway no free tier (Trial com crédito de US$ 5, depois plano Free; ver [deploy/INSTRUCOES.md](deploy/INSTRUCOES.md)) | Plataforma publicada com HTTPS sem gastar | Recursos limitados e serviços que dormem quando ociosos: a primeira requisição depois de um tempo parado é mais lenta. |
| Modelo local (scikit-learn), treinado no build da imagem | Nenhum custo por requisição de API de IA; funciona offline | Modelo simples. Trocar por um LLM pago passaria a cobrar por chamada e aumentaria muito a latência, o que reforça a escolha da fila. |
| Um único Redis para fila, resultados e rate limit | Um serviço gerenciado a menos para pagar e operar | Ponto único de falha: se cair, `/predict` e `/resultado` param (o rate limit continua em memória). |
| Embeddings TF-IDF locais em vez de API de embeddings | Sem custo de API nem download de modelo | Cada indexação recalcula os vetores da base inteira (O(n)): barato para centenas de documentos, inviável para milhões. |
| Réplicas de worker | Mais vazão | Cada réplica consome crédito mesmo ociosa; no free tier mantemos 2. O próximo passo seria escalar pelo tamanho da fila. |
| Jaeger só no ambiente local | Não gasta crédito do Railway com um coletor | Em produção não há traces armazenados; para isso seria preciso um coletor/serviço de tracing gerenciado. |
| TTL nos resultados (1 h) | Memória do Redis não cresce sem limite | O cliente precisa buscar o resultado dentro do prazo. Também atende à LGPD. |
