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

Sobem 6 containers: `redis`, `inferencia`, `vetorial`, `gateway` e 2 réplicas de
`worker`. O gateway só passa a aceitar requisições depois que a inferência e o
armazenamento vetorial estão saudáveis.
Apenas o gateway fica exposto, em `http://localhost:8000`.

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
