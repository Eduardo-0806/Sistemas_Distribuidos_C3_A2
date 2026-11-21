# Deploy em nuvem — Railway

A plataforma inteira roda no Railway, com a **mesma arquitetura do compose**:
5 serviços + Redis num único projeto. Só o gateway tem domínio público (HTTPS
automático do Railway); os demais conversam pela **rede privada**
(`<servico>.railway.internal`) e não são acessíveis pela internet.

```
internet --HTTPS--> gateway (dominio publico)
                       |-- http://inferencia.railway.internal:8001 --RPUSH--> Redis
                       |                                worker (N) <--BLPOP--+
                       +-- http://vetorial.railway.internal:8002  (volume /dados)
```

**Custo:** conta nova começa no Trial (30 dias, crédito único de US$ 5, sem
cartão). Depois cai no plano Free (US$ 1/mês, serviços dormem quando ociosos).

## 1. Criar o projeto

1. Entre em <https://railway.com> com a conta do GitHub.
2. **New Project → Deploy from GitHub repo** → `Sistemas_Distribuidos_C3_A2`.
   Isso cria o primeiro serviço; ele vira o `gateway` (passo 2).
3. No canvas do projeto, **+ Create → Database → Redis**.

Os serviços restantes: **+ Create → GitHub Repo →** o mesmo repositório.
Renomeie cada um (Settings → nome) **exatamente** como na tabela: os nomes
viram os endereços internos (`inferencia.railway.internal` etc.).

## 2. Configuração de cada serviço

Em todos: **Settings → Source → Root Directory** e **Variables** como abaixo.
`${{Redis.REDIS_URL}}` e `${{inferencia.RAILWAY_PRIVATE_DOMAIN}}` são
*reference variables*: o Railway preenche sozinho.

### `inferencia`
- Root Directory: `/` (raiz — o build usa a pasta `comum/`)
- Variables:
  ```
  RAILWAY_DOCKERFILE_PATH=/inferencia/Dockerfile
  HOST=::
  PORT=8001
  REDIS_URL=${{Redis.REDIS_URL}}
  RESULTADO_TTL_S=3600
  ```
- Sem domínio público.

### `worker`
- Root Directory: `/`
- Variables:
  ```
  RAILWAY_DOCKERFILE_PATH=/worker/Dockerfile
  REDIS_URL=${{Redis.REDIS_URL}}
  RESULTADO_TTL_S=3600
  ```
- Settings → Deploy → **Replicas: 2** (vários workers na mesma fila).
- Sem domínio público.

### `vetorial`
- Root Directory: `/vetorial`
- Variables:
  ```
  HOST=::
  PORT=8002
  RAILWAY_RUN_UID=0
  ```
  (`RAILWAY_RUN_UID=0`: o Railway monta volumes como root; sem isso o
  usuário sem privilégio do container não consegue gravar o índice.)
- Clique com o botão direito no serviço → **Attach Volume** → mount path `/dados`.
- Sem domínio público.

### `gateway`
- Root Directory: `/gateway`
- Variables:
  ```
  PORT=8000
  URL_INFERENCIA=http://${{inferencia.RAILWAY_PRIVATE_DOMAIN}}:8001
  URL_VETORIAL=http://${{vetorial.RAILWAY_PRIVATE_DOMAIN}}:8002
  REDIS_URL=${{Redis.REDIS_URL}}
  JWT_SEGREDO=<valor forte e aleatorio>
  JWT_EXPIRACAO_MIN=30
  AUTH_USUARIO=admin
  AUTH_SENHA=<senha forte>
  LIMITE_REQ_POR_MIN=30
  LIMITE_LOGIN_POR_MIN=10
  FORWARDED_ALLOW_IPS=*
  ```
  - Gere o segredo com `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
  - `FORWARDED_ALLOW_IPS=*`: o gateway fica atrás do proxy do Railway; com
    isso o uvicorn usa o IP real do `X-Forwarded-For` e o rate limit do
    `/login` passa a ser por cliente, não pelo IP do proxy.
- Settings → Networking → **Generate Domain** → porta `8000`.
  O endereço `https://<nome>.up.railway.app` já sai com **HTTPS** (tarefa 8).

## 3. Deploy

Clique em **Deploy** (ou *Apply changes*). Ordem natural: Redis → inferência /
vetorial / worker → gateway. Acompanhe em **Deployments → View logs**:

- inferência: `[inferencia] modelo carregado em ...`
- worker: `[worker] pronto. aguardando tarefas`
- vetorial: `[vetorial] indice inicial: 3 documentos`
- gateway: `Uvicorn running on http://0.0.0.0:8000`

A cada `git push` na `main`, o Railway refaz o deploy sozinho.

## 4. Testar a URL pública

```bash
python deploy/testar_deploy.py https://<seu-gateway>.up.railway.app admin <AUTH_SENHA>
```

O script faz login, envia um texto para a fila, espera o worker responder,
busca na base vetorial e confere o 401 sem token. Tudo `OK` = publicado.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `/predict` devolve `503 servico de inferencia indisponivel` | `HOST=::` ou `PORT=8001` faltando na inferência, ou nome do serviço diferente de `inferencia` |
| Vetorial reinicia com `PermissionError: /dados/...` | faltou `RAILWAY_RUN_UID=0` |
| Build da inferência/worker falha com `comum/ not found` | Root Directory não está em `/` |
| Gateway não sobe: `Variavel de ambiente JWT_SEGREDO nao definida` | variáveis do gateway faltando |
| Domínio responde 502 | domínio gerado com porta diferente de `8000` |
