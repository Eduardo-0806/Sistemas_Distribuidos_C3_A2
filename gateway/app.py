"""
API Gateway - porta de entrada unica da plataforma.

JA PRONTO: roteamento para o servico de inferencia e log de requisicoes.
TAREFA 1 (feita): autenticacao por JWT.
    - POST /login  -> valida usuario/senha e emite um token JWT (HS256).
    - Rotas protegidas exigem o cabecalho "Authorization: Bearer <token>";
      sem token, ou com token invalido/expirado, a resposta e 401.
    - /saude continua publica (usada por healthcheck do compose e da nuvem).
TAREFA 2 (feita): limite de requisicoes por cliente (rate limit), ver limitador.py.
    - Rotas protegidas: limite por USUARIO autenticado (claim "sub" do JWT).
    - /login: limite por IP (freia tentativa de senha por forca bruta).
    - Estourou -> 429 com Retry-After. Toda resposta limitada traz os
      cabecalhos X-RateLimit-Limit / -Remaining / -Reset.
    - Contadores no Redis (compartilhados entre replicas do gateway); sem
      Redis, ou com o Redis fora do ar, conta em memoria.
    - LGPD: usuario e IP viram um HMAC antes de virar chave no Redis.
TAREFA 4 (feita): roteamento do fluxo assincrono (fila + worker).
    - POST /predict          -> inferencia enfileira; devolve 202 + {"id"}
                                e o cabecalho Location: /resultado/<id>
    - GET  /resultado/{id}   -> na_fila | pronto (com o resultado) | erro;
                                404 se nao existe/expirou
    - O gateway repassa o status da inferencia (400, 404...) e so troca por
      503 quando nao consegue falar com ela.

Configuracao (toda via variaveis de ambiente):
    JWT_SEGREDO           segredo de assinatura do token (OBRIGATORIO)
    JWT_EXPIRACAO_MIN     validade do token em minutos (padrao: 30)
    AUTH_USUARIO          usuario aceito no /login (OBRIGATORIO)
    AUTH_SENHA            senha aceita no /login (OBRIGATORIO)
    URL_INFERENCIA        endereco do servico de inferencia
    REDIS_URL             Redis dos contadores (vazio = memoria local)
    LIMITE_REQ_POR_MIN    requisicoes/min por usuario nas rotas protegidas (30)
    LIMITE_LOGIN_POR_MIN  tentativas de login/min por IP (10)

Rodar: uvicorn app:app --port 8000
"""
import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import requests
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from limitador import criar_limitador


def _env_obrigatoria(nome: str) -> str:
    """Le uma variavel de ambiente obrigatoria; falha cedo se estiver vazia."""
    valor = os.getenv(nome, "").strip()
    if not valor:
        raise RuntimeError(
            f"Variavel de ambiente {nome} nao definida. "
            f"Copie .env.example para .env e preencha os valores.")
    return valor


URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://localhost:8001")
JWT_SEGREDO = _env_obrigatoria("JWT_SEGREDO")
JWT_ALGORITMO = "HS256"
JWT_EMISSOR = "gateway-c3a2"
JWT_EXPIRACAO_MIN = int(os.getenv("JWT_EXPIRACAO_MIN", "30"))
AUTH_USUARIO = _env_obrigatoria("AUTH_USUARIO")
AUTH_SENHA = _env_obrigatoria("AUTH_SENHA")
LIMITE_REQ_POR_MIN = int(os.getenv("LIMITE_REQ_POR_MIN", "30"))
LIMITE_LOGIN_POR_MIN = int(os.getenv("LIMITE_LOGIN_POR_MIN", "10"))
JANELA_LIMITE_S = 60
limitador = criar_limitador(os.getenv("REDIS_URL", "").strip())

app = FastAPI(title="Gateway - C3.A2")

# auto_error=False: sem isso o FastAPI responde 403 quando o cabecalho falta;
# o edital pede 401, entao tratamos a ausencia manualmente.
esquema_bearer = HTTPBearer(auto_error=False)


class Entrada(BaseModel):
    texto: str


class Credenciais(BaseModel):
    usuario: str
    senha: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_em: int  # segundos


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def _nao_autorizado(motivo: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=motivo,
        headers={"WWW-Authenticate": "Bearer"},
    )


def emitir_token(sujeito: str) -> str:
    agora = datetime.now(timezone.utc)
    claims = {
        "sub": sujeito,
        "iss": JWT_EMISSOR,
        "iat": agora,
        "exp": agora + timedelta(minutes=JWT_EXPIRACAO_MIN),
    }
    return jwt.encode(claims, JWT_SEGREDO, algorithm=JWT_ALGORITMO)


def exigir_token(
    cred: HTTPAuthorizationCredentials | None = Depends(esquema_bearer),
) -> dict:
    """Dependencia que protege rotas: devolve as claims ou levanta 401."""
    if cred is None or cred.scheme.lower() != "bearer" or not cred.credentials:
        raise _nao_autorizado("token ausente")
    try:
        return jwt.decode(
            cred.credentials,
            JWT_SEGREDO,
            algorithms=[JWT_ALGORITMO],  # lista fixa: impede ataque "alg=none"
            issuer=JWT_EMISSOR,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise _nao_autorizado("token expirado")
    except jwt.InvalidTokenError:
        raise _nao_autorizado("token invalido")


# --------------------------------------------------------------------------
# Rate limit
# --------------------------------------------------------------------------
def _anonimizar(valor: str) -> str:
    """HMAC do identificador: o Redis nunca guarda usuario ou IP em claro."""
    return hmac.new(JWT_SEGREDO.encode(), valor.encode(),
                    hashlib.sha256).hexdigest()[:24]


def _aplicar_limite(escopo: str, identificador: str, limite: int,
                    response: Response) -> None:
    res = limitador.registrar(f"{escopo}:{_anonimizar(identificador)}",
                              limite, JANELA_LIMITE_S)
    cabecalhos = {
        "X-RateLimit-Limit": str(res.limite),
        "X-RateLimit-Remaining": str(res.restantes),
        "X-RateLimit-Reset": str(res.reset_em),
    }
    if not res.permitido:
        cabecalhos["Retry-After"] = str(res.reset_em)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"limite de {res.limite} requisicoes por minuto excedido; "
                   f"tente novamente em {res.reset_em}s",
            headers=cabecalhos,
        )
    response.headers.update(cabecalhos)


def limitar_por_usuario(response: Response,
                        claims: dict = Depends(exigir_token)) -> dict:
    """Autentica (401) e depois aplica o limite do usuario (429)."""
    _aplicar_limite("api", claims["sub"], LIMITE_REQ_POR_MIN, response)
    return claims


def limitar_por_ip(request: Request, response: Response) -> None:
    # Atras de proxy (Render/Railway) o IP real vem do X-Forwarded-For; o
    # uvicorn so confia nesse cabecalho se o proxy estiver em
    # FORWARDED_ALLOW_IPS (configurar no deploy, TAREFA 5).
    ip = request.client.host if request.client else "desconhecido"
    _aplicar_limite("login", ip, LIMITE_LOGIN_POR_MIN, response)


# --------------------------------------------------------------------------
# Middleware de log (sem dados pessoais: so metodo, rota, status e tempo)
# --------------------------------------------------------------------------
@app.middleware("http")
async def registrar(request: Request, call_next):
    inicio = time.time()
    resposta = await call_next(request)
    ms = (time.time() - inicio) * 1000
    print(f"[gateway] {request.method} {request.url.path} "
          f"-> {resposta.status_code} ({ms:.1f}ms)")
    return resposta


# --------------------------------------------------------------------------
# Rotas publicas
# --------------------------------------------------------------------------
@app.get("/saude")
def saude():
    return {"status": "ok"}


@app.post("/login", response_model=Token,
          dependencies=[Depends(limitar_por_ip)])
def login(cred: Credenciais):
    # compare_digest: comparacao em tempo constante (evita ataque de timing).
    usuario_ok = hmac.compare_digest(cred.usuario.encode(), AUTH_USUARIO.encode())
    senha_ok = hmac.compare_digest(cred.senha.encode(), AUTH_SENHA.encode())
    if not (usuario_ok and senha_ok):
        # Mensagem generica: nao revela se o erro foi no usuario ou na senha.
        raise _nao_autorizado("credenciais invalidas")
    return Token(access_token=emitir_token(cred.usuario),
                 expira_em=JWT_EXPIRACAO_MIN * 60)


# --------------------------------------------------------------------------
# Rotas protegidas (exigem JWT)
# --------------------------------------------------------------------------
def _encaminhar(metodo: str, caminho: str, response: Response, **kwargs):
    """Repassa a chamada para a inferencia, preservando o status da resposta.

    Usa o `response` injetado (em vez de devolver um JSONResponse) para que os
    cabecalhos de rate limit definidos na dependencia continuem na resposta.
    """
    try:
        r = requests.request(metodo, f"{URL_INFERENCIA}{caminho}",
                             timeout=10, **kwargs)
    except requests.RequestException as e:
        # Log so com o tipo do erro: a mensagem pode conter dados da requisicao.
        print(f"[gateway] inferencia inacessivel: {type(e).__name__}")
        raise HTTPException(status_code=503,
                            detail="servico de inferencia indisponivel")
    try:
        corpo = r.json()
    except ValueError:
        raise HTTPException(status_code=502,
                            detail="resposta invalida do servico de inferencia")
    response.status_code = r.status_code
    return corpo


@app.post("/predict", status_code=status.HTTP_202_ACCEPTED)
def predict(entrada: Entrada, response: Response,
            claims: dict = Depends(limitar_por_usuario)):
    """Enfileira a inferencia; consulte o resultado em GET /resultado/{id}."""
    corpo = _encaminhar("POST", "/predict", response, json=entrada.model_dump())
    if response.status_code == status.HTTP_202_ACCEPTED and "id" in corpo:
        response.headers["Location"] = f"/resultado/{corpo['id']}"
    return corpo


@app.get("/resultado/{tarefa_id}")
def resultado(tarefa_id: uuid.UUID, response: Response,
              claims: dict = Depends(limitar_por_usuario)):
    """Status/resultado da tarefa. Id que nao e UUID -> 422 (nem chega a inferencia)."""
    return _encaminhar("GET", f"/resultado/{tarefa_id}", response)
