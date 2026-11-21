"""
Testes da TAREFA 1 (JWT no gateway).

Rodar (dentro de gateway/):
    pip install -r requirements.txt -r requirements-dev.txt
    pytest -q
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest

os.environ.update(
    JWT_SEGREDO="segredo-de-teste-com-tamanho-suficiente-123",
    AUTH_USUARIO="aluno",
    AUTH_SENHA="senha-teste",
    JWT_EXPIRACAO_MIN="5",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as gateway  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

cliente = TestClient(gateway.app)


def _login(usuario="aluno", senha="senha-teste"):
    return cliente.post("/login", json={"usuario": usuario, "senha": senha})


def _token():
    return _login().json()["access_token"]


class _RespostaFalsa:
    def raise_for_status(self):
        pass

    def json(self):
        return {"sentimento": "positivo"}


@pytest.fixture
def inferencia_falsa(monkeypatch):
    chamadas = []

    def post_falso(url, json, timeout):
        chamadas.append((url, json))
        return _RespostaFalsa()

    monkeypatch.setattr(gateway.requests, "post", post_falso)
    return chamadas


def test_saude_e_publica():
    assert cliente.get("/saude").status_code == 200


def test_login_ok_emite_token_valido():
    r = _login()
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["token_type"] == "bearer"
    assert corpo["expira_em"] == 300
    claims = jwt.decode(corpo["access_token"], gateway.JWT_SEGREDO,
                        algorithms=["HS256"], issuer="gateway-c3a2")
    assert claims["sub"] == "aluno"


@pytest.mark.parametrize("usuario,senha", [
    ("aluno", "errada"), ("outro", "senha-teste"), ("", "")])
def test_login_credenciais_invalidas_401(usuario, senha):
    r = _login(usuario, senha)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_predict_sem_token_401(inferencia_falsa):
    r = cliente.post("/predict", json={"texto": "oi"})
    assert r.status_code == 401
    assert r.json()["detail"] == "token ausente"
    assert inferencia_falsa == []  # nem chegou a chamar a inferencia


@pytest.mark.parametrize("cabecalho", [
    "Bearer abc.def.ghi", "Bearer ", "Basic dXNlcjpwYXNz", "tokensemesquema"])
def test_predict_token_malformado_401(cabecalho, inferencia_falsa):
    r = cliente.post("/predict", json={"texto": "oi"},
                     headers={"Authorization": cabecalho})
    assert r.status_code == 401
    assert inferencia_falsa == []


def test_predict_token_assinado_com_outro_segredo_401(inferencia_falsa):
    agora = datetime.now(timezone.utc)
    falso = jwt.encode({"sub": "aluno", "iss": "gateway-c3a2", "iat": agora,
                        "exp": agora + timedelta(minutes=5)},
                       "outro-segredo-qualquer-com-bastante-tamanho",
                       algorithm="HS256")
    r = cliente.post("/predict", json={"texto": "oi"},
                     headers={"Authorization": f"Bearer {falso}"})
    assert r.status_code == 401
    assert r.json()["detail"] == "token invalido"


def test_predict_token_expirado_401(inferencia_falsa):
    passado = datetime.now(timezone.utc) - timedelta(hours=1)
    velho = jwt.encode({"sub": "aluno", "iss": "gateway-c3a2", "iat": passado,
                        "exp": passado + timedelta(minutes=5)},
                       gateway.JWT_SEGREDO, algorithm="HS256")
    r = cliente.post("/predict", json={"texto": "oi"},
                     headers={"Authorization": f"Bearer {velho}"})
    assert r.status_code == 401
    assert r.json()["detail"] == "token expirado"


def test_predict_token_alg_none_401(inferencia_falsa):
    sem_assinatura = jwt.encode({"sub": "aluno", "iss": "gateway-c3a2"},
                                key=None, algorithm="none")
    r = cliente.post("/predict", json={"texto": "oi"},
                     headers={"Authorization": f"Bearer {sem_assinatura}"})
    assert r.status_code == 401


def test_predict_com_token_valido_repassa_para_inferencia(inferencia_falsa):
    r = cliente.post("/predict", json={"texto": "servico excelente"},
                     headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    assert r.json() == {"sentimento": "positivo"}
    assert inferencia_falsa[0][1] == {"texto": "servico excelente"}


def test_falha_cedo_sem_segredo(monkeypatch):
    monkeypatch.delenv("JWT_SEGREDO", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SEGREDO"):
        gateway._env_obrigatoria("JWT_SEGREDO")
