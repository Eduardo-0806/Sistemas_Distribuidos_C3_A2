"""
API Gateway - porta de entrada unica da plataforma.

JA PRONTO: roteamento para o servico de inferencia e log de requisicoes.
TAREFA 1 (feita): autenticacao por JWT.
    - POST /login  -> valida usuario/senha e emite um token JWT (HS256).
    - Rotas protegidas exigem o cabecalho "Authorization: Bearer <token>";
      sem token, ou com token invalido/expirado, a resposta e 401.
    - /saude continua publica (usada por healthcheck do compose e da nuvem).
TAREFA 2: limite de requisicoes por cliente (rate limit).

Configuracao (toda via variaveis de ambiente):
    JWT_SEGREDO         segredo de assinatura do token (OBRIGATORIO)
    JWT_EXPIRACAO_MIN   validade do token em minutos (padrao: 30)
    AUTH_USUARIO        usuario aceito no /login (OBRIGATORIO)
    AUTH_SENHA          senha aceita no /login (OBRIGATORIO)
    URL_INFERENCIA      endereco do servico de inferencia

Rodar: uvicorn app:app --port 8000
"""
import hmac
import os
import time
from datetime import datetime, timedelta, timezone

import jwt
import requests
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel


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


@app.post("/login", response_model=Token)
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
@app.post("/predict")
def predict(entrada: Entrada, claims: dict = Depends(exigir_token)):
    # TAREFA 2: aplicar limite de requisicoes por cliente (claims["sub"]).
    try:
        r = requests.post(f"{URL_INFERENCIA}/predict",
                          json=entrada.model_dump(), timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=503,
                            detail=f"servico de inferencia indisponivel: {e}")
