# Kit de Partida — C3.A2: Plataforma de IA como Serviço (projeto integrador)

**Sistemas Distribuídos e Computação em Nuvem · FAESA · 2026/2**
Prof. Howard Cruz Roatti · Lançado na Aula 13 (05/11) · Entrega na Aula 17 (26/11)

---

## O que é isto

O projeto que fecha o semestre. Você pega tudo o que construiu e transforma numa
plataforma de verdade: **conteinerizada, publicada na internet, observável e protegida**.
Ao final você terá um sistema distribuído completo e público — material de portfólio
para entrevista de emprego.

> **Sobre a IA neste trabalho:** todo contato com inteligência artificial aqui é
> **chamada de biblioteca ou de API**. Você **não vai treinar modelos** nem precisar de
> matemática de aprendizado de máquina. O modelo já vem pronto e configurado.
> A sua nota vem da **engenharia distribuída**: arquitetura, comunicação, resiliência e
> execução reproduzível — a sofisticação do modelo **não pontua**.

---

## Plataforma publicada

**URL pública (Railway, HTTPS):** <https://gateway-production-e512e82f.up.railway.app>  
(saúde: [https://gateway-production-e512e82f.up.railway.app/saude](https://gateway-production-e512e82f.up.railway.app/saude) · documentação interativa: [https://gateway-production-e512e82f.up.railway.app/docs](https://gateway-production-e512e82f.up.railway.app/docs))

Os 5 serviços + Redis rodam no Railway com a mesma arquitetura do compose; só o
gateway é público, os demais usam a rede privada do Railway. Passo a passo em
[deploy/INSTRUCOES.md](deploy/INSTRUCOES.md). Teste ponta a ponta:

```bash
python deploy/testar_deploy.py https://<url-publica> admin <senha>
```

---

## Arquitetura

```
cliente --HTTPS--> gateway:8000 --HTTP--> inferencia:8001 --RPUSH--> Redis (fila "tarefas")
                   (JWT, rate limit,  |                                  |
                    timeout, retry,   |         worker (N réplicas) <--BLPOP
                    circuit breaker)  |            grava resultado:<id> no Redis (TTL)
                                      |
                                      +--HTTP--> vetorial:8002 (índice em volume)

            todos os serviços --OTLP--> Jaeger (rastreamento distribuído)
```

| Serviço | Papel |
|---|---|
| `gateway` | Única porta de entrada. Autentica (JWT), limita requisições por usuário/IP (contadores no Redis) e roteia para os serviços internos com tempo-limite, retentativa e circuit breaker. |
| `inferencia` | Recebe o texto, enfileira a tarefa no Redis e devolve `202` com um `id`; consulta o resultado em `/resultado/{id}`. |
| `worker` | Consome a fila (`BLPOP`), roda o modelo e grava o resultado com expiração. Escala horizontalmente: cada tarefa vai para um worker só. |
| `vetorial` | Armazenamento vetorial: indexa documentos (TF-IDF), persiste o índice em volume e faz busca por similaridade. |
| `redis` | Fila de tarefas, resultados (com TTL) e contadores do rate limit. |
| `jaeger` | Recebe e exibe os traces (só no ambiente local). |

**Comunicação:** REST síncrono entre gateway e serviços; mensageria assíncrona
(fila no Redis) entre inferência e worker. Os serviços se encontram pelo nome
(`http://inferencia:8001`), nunca por IP fixo.

**Resiliência** (`gateway/resiliencia.py`, configurável no `.env`):
- **Tempo-limite** em toda chamada interna (`SERVICO_TIMEOUT_S`, padrão 10 s).
- **Retentativa com espera exponencial** (0,2 s → 0,4 s → ..., até `SERVICO_BACKOFF_MAX_S`)
  só nas chamadas seguras de repetir (`GET /resultado` e `POST /buscar`). `POST /predict`
  e `POST /documentos` não são repetidos para não duplicar tarefas/documentos.
- **Circuit breaker por serviço:** após `DISJUNTOR_LIMITE_FALHAS` (5) falhas seguidas o
  disjuntor abre e o gateway responde `503` na hora, sem chamar o serviço, por
  `DISJUNTOR_DESCANSO_S` (30 s); depois deixa passar uma sondagem (meia-abertura).
  Como há um disjuntor por serviço, a queda da inferência não afeta a busca vetorial.

**Observabilidade:** todos os serviços são instrumentados com OpenTelemetry
(`opentelemetry-instrument`). O contexto do trace viaja dentro da mensagem da
fila, então um único trace cobre **gateway → inferência → fila (`fila.publicar`,
`fila.espera`) → worker (`worker.processar`)**. Para ver: suba o compose, faça um
`/predict` e abra <http://localhost:16686> (serviço `gateway`). A resposta do
gateway traz o cabeçalho `X-Trace-Id` para achar o trace da requisição.

Decisões e limitações (CAP, custo e latência) estão no
[relatório de trade-offs](RELATORIO_TRADEOFFS.md).

---

## Como executar do zero

**Pré-requisito:** apenas [Docker](https://docs.docker.com/get-docker/) com o Compose
(no Windows, Docker Desktop com WSL 2). Não é preciso instalar Python.

```bash
# 1. Clone e entre na pasta
git clone https://github.com/Eduardo-0806/Sistemas_Distribuidos_C3_A2.git
cd Sistemas_Distribuidos_C3_A2

# 2. (Opcional) Ajuste segredos e limites. Sem .env, valem os padrões do compose.
cp .env.example .env

# 3. Suba o sistema inteiro com UM comando
docker compose up --build
```

Sobem 7 containers: `redis`, `jaeger`, `inferencia`, `vetorial`, `gateway` e 2
réplicas de `worker`. O gateway só passa a aceitar requisições depois que a
inferência e o armazenamento vetorial estão saudáveis.
A API fica exposta só pelo gateway, em `http://localhost:8000`; a interface do
Jaeger (traces) fica em `http://localhost:16686`.

### Testando (sempre pelo gateway)

```bash
# Rota pública
curl http://localhost:8000/saude

# 1. Login (AUTH_USUARIO / AUTH_SENHA) -> token JWT
TOKEN=$(curl -s -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"usuario":"admin","senha":"troque-esta-senha"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Envia o texto: a tarefa vai para a fila -> 202 {"id": "...", "status": "na_fila"}
curl -i -X POST http://localhost:8000/predict \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"texto":"servico excelente"}'

# 3. Consulta o resultado com o id recebido (um worker processa em milissegundos)
curl http://localhost:8000/resultado/<id> -H "Authorization: Bearer $TOKEN"
# -> {"id": "...", "status": "pronto", "sentimento": "positivo", "confianca": 0.58, ...}

# 4. Armazenamento vetorial: busca por similaridade (já vem com 3 documentos)
curl -X POST http://localhost:8000/buscar -H "Authorization: Bearer $TOKEN"   -H "Content-Type: application/json" -d '{"pergunta":"o que diz o teorema CAP?","top_k":2}'

# 5. Indexa novos documentos (persistem no volume do serviço vetorial) -> 201
curl -X POST http://localhost:8000/documentos -H "Authorization: Bearer $TOKEN"   -H "Content-Type: application/json"   -d '[{"texto":"Circuit breaker abre apos falhas seguidas.","origem":"aula11"}]'
```

| Situação | Resposta |
|---|---|
| Rota protegida sem token, ou com token inválido/expirado | `401` |
| Texto vazio | `400` |
| Corpo inválido em `/documentos` ou `/buscar` (lista vazia, `top_k` > 20...) | `422` |
| `id` inexistente ou expirado (após `RESULTADO_TTL_S`) | `404` |
| Mais de `LIMITE_REQ_POR_MIN` por usuário, ou de `LIMITE_LOGIN_POR_MIN` logins por IP | `429` + `Retry-After` |
| Inferência ou armazenamento vetorial fora do ar | `503` |

### Comandos úteis

```bash
docker compose ps                        # estado e healthcheck de cada serviço
docker compose logs -f worker            # acompanhar os workers
docker compose up -d --scale worker=4    # mais workers consumindo a fila
docker compose down                      # parar (mantém os volumes de dados)
docker compose down -v                   # parar e apagar Redis e índice vetorial
```

Publicação na nuvem: veja [deploy/INSTRUCOES.md](deploy/INSTRUCOES.md).

---

## Conformidade (LGPD)

A plataforma segue o princípio da **minimização**: guarda só o necessário para
responder ao cliente, pelo menor tempo possível, e nada de conteúdo vai para logs.

| Dado | Onde fica | Finalidade | Por quanto tempo |
|---|---|---|---|
| Texto enviado ao `/predict` | Redis, na fila `tarefas` | Ser classificado pelo worker | Até um worker consumir a tarefa (milissegundos com os workers no ar). Sai da fila no `BLPOP` e **não** é copiado para o resultado. Se nenhum worker estiver no ar, espera na fila até ser consumido. |
| Resultado da inferência (`sentimento`, `confianca`, `status`, `tempo_ms`) | Redis, chave `resultado:<id>` | Permitir que o cliente consulte o resultado da tarefa assíncrona | `RESULTADO_TTL_S` (padrão **1 hora**); depois o Redis apaga sozinho e a consulta devolve `404`. |
| Pergunta do `/buscar` | Só na memória durante a requisição | Calcular a similaridade | Não é armazenada. |
| Documentos enviados ao `/documentos` (`texto`, `origem`) | Volume do serviço vetorial (`/dados/indice.json`) | Compor a base de busca | Até serem removidos pelo administrador (`docker compose down -v` ou remoção do volume no Railway). A base é de conteúdo técnico: **não indexe dados pessoais**. |
| Usuário e senha do `/login` | Comparados em memória com `AUTH_USUARIO`/`AUTH_SENHA` (variáveis de ambiente) | Autenticação | Nunca gravados nem logados. |
| Token JWT (contém o usuário em `sub`) | Só com o cliente; o servidor não guarda tokens | Autorizar as rotas protegidas | Expira em `JWT_EXPIRACAO_MIN` (padrão **30 min**). |
| Usuário e IP para o rate limit | Redis, como **HMAC-SHA256** (nunca em claro) | Limitar abuso e força bruta no login | Uma chave por janela de 60 s; o Redis a apaga sozinho em no máximo ~2 min. |
| Logs dos serviços | Saída padrão dos containers | Operação e diagnóstico | Só método, rota, status, tempo e id da tarefa — **sem texto e sem IP** (o log de acesso do uvicorn, que gravaria o IP, está desligado). Ficam enquanto o container existir (local) ou pelo período de retenção de logs do plano no Railway. |
| Traces (OpenTelemetry/Jaeger) | Jaeger local | Diagnóstico de latência e falhas | Rota, status, duração, id da tarefa e user-agent; comandos do Redis vão sanitizados (sem valores). O Jaeger do compose guarda em memória: some ao reiniciar o container. |

Além disso: só o gateway é exposto, com **HTTPS** no deploy público; os demais
serviços ficam na rede interna. Segredos (`JWT_SEGREDO`, `AUTH_SENHA`) ficam em
variáveis de ambiente e o `.env` está no `.gitignore`. O proxy de borda do
Railway pode registrar IPs em seus próprios logs de plataforma, fora do controle
da aplicação.

---

## Estrutura do projeto

```
Sistemas_Distribuidos_C3_A2/
├── gateway/                # porta de entrada: JWT, rate limit, roteamento
│   ├── app.py
│   ├── limitador.py        # rate limit (Redis, com reserva em memória)
│   └── Dockerfile
├── inferencia/             # API REST que enfileira e consulta resultados
│   ├── app.py
│   └── Dockerfile
├── worker/                 # consome a fila e roda o modelo
│   ├── worker.py
│   └── Dockerfile
├── vetorial/               # armazenamento vetorial: indexa, persiste e busca
│   ├── app.py
│   ├── embeddings.py       # vetorização TF-IDF (offline)
│   ├── documentos/         # base inicial indexada na primeira subida
│   └── Dockerfile
├── comum/                  # modelo e fila (compartilhados por inferência e worker)
├── deploy/                 # passo a passo do Railway + testar_deploy.py
├── docker-compose.yml      # o sistema inteiro com um comando
├── RELATORIO_TRADEOFFS.md  # CAP, custo e latência
└── TAREFAS.md
```

---

## O que você precisa fazer

Abra o arquivo **`TAREFAS.md`**: ele lista o núcleo obrigatório item a item, indicando
o arquivo e a aula de referência de cada um.

---

## Como você será avaliado

| Critério | Pontos |
|---|---|
| Arquitetura e decomposição em serviços | 1,5 |
| Comunicação funcionando (REST / gRPC / mensageria) | 1,5 |
| Resiliência e tratamento de falhas | 1,0 |
| Execução reproduzível (README, container, deploy) | 1,0 |
| **Sofisticação do modelo de IA** | **não pontua** |
| **Total** | **5,0** |

**Entrega:** no seu repositório do GitHub, **sem apresentação oral**. Grupos livres.

---

## Aulas de referência

- **Aula 13** — Nuvem, containers e o primeiro deploy
- **Aula 14** — Orquestração, serverless e borda
- **Aula 15** — Observabilidade e rastreamento distribuído
- **Aula 16** — Segurança, LGPD e revisão para o ENADE

---

## Dúvidas frequentes

**Preciso saber machine learning?** Não. O modelo já está pronto e você só chama uma função.

**E se eu não tiver internet no laboratório?** Tudo neste kit funciona offline. O modelo é
treinado localmente e o cliente de LLM tem modo simulado.

**Posso trocar a linguagem?** O kit é em Python porque é o ecossistema usado nas aulas.
Se quiser usar outra linguagem, converse com o professor antes.

**Posso usar IA para me ajudar a programar?** Sim. Este é um trabalho prático feito fora de
sala, e usar ferramentas de IA é realista. O que se avalia é o **sistema funcionando** e as
**decisões de arquitetura** — que você precisa saber explicar.
