"""
Testes da TAREFA 2 (rate limit no gateway).

Rodar (dentro de gateway/):
    pip install -r requirements.txt -r requirements-dev.txt
    pytest -q
"""
import fakeredis
import pytest
import redis
from fastapi.testclient import TestClient

import app as gateway  # ambiente configurado em conftest.py
from limitador import (LimitadorComReserva, LimitadorMemoria, LimitadorRedis,
                       criar_limitador)

cliente = TestClient(gateway.app)


def _cab(sujeito="aluno"):
    return {"Authorization": f"Bearer {gateway.emitir_token(sujeito)}"}


def _predict(cab):
    return cliente.post("/predict", json={"texto": "oi"}, headers=cab)


class _RespostaFalsa:
    def raise_for_status(self):
        pass

    def json(self):
        return {"sentimento": "positivo"}


@pytest.fixture
def inferencia_falsa(monkeypatch):
    chamadas = []

    def post_falso(url, json, timeout):
        chamadas.append(json)
        return _RespostaFalsa()

    monkeypatch.setattr(gateway.requests, "post", post_falso)
    return chamadas


@pytest.fixture
def limite_3(monkeypatch):
    monkeypatch.setattr(gateway, "LIMITE_REQ_POR_MIN", 3)
    monkeypatch.setattr(gateway, "LIMITE_LOGIN_POR_MIN", 3)


# ---------------------------------------------------------------- via HTTP
def test_predict_dentro_do_limite_traz_cabecalhos(inferencia_falsa, limite_3):
    r = _predict(_cab())
    assert r.status_code == 200
    assert r.headers["x-ratelimit-limit"] == "3"
    assert r.headers["x-ratelimit-remaining"] == "2"
    assert 1 <= int(r.headers["x-ratelimit-reset"]) <= 60


def test_predict_acima_do_limite_429(inferencia_falsa, limite_3):
    cab = _cab()
    assert [_predict(cab).status_code for _ in range(3)] == [200, 200, 200]
    r = _predict(cab)
    assert r.status_code == 429
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert r.headers["x-ratelimit-remaining"] == "0"
    assert len(inferencia_falsa) == 3  # a 4a nem chegou na inferencia


def test_limite_e_por_usuario(inferencia_falsa, limite_3):
    for _ in range(3):
        _predict(_cab("aluno"))
    assert _predict(_cab("aluno")).status_code == 429
    assert _predict(_cab("outro")).status_code == 200


def test_sem_token_continua_401_mesmo_apos_limite(inferencia_falsa, limite_3):
    for _ in range(4):
        _predict(_cab())
    assert cliente.post("/predict", json={"texto": "oi"}).status_code == 401


def test_login_limitado_por_ip_contra_forca_bruta(limite_3):
    errado = {"usuario": "aluno", "senha": "chute"}
    assert [cliente.post("/login", json=errado).status_code
            for _ in range(3)] == [401, 401, 401]
    certo = {"usuario": "aluno", "senha": "senha-teste"}
    r = cliente.post("/login", json=certo)
    assert r.status_code == 429  # bloqueado ate a janela virar
    assert "retry-after" in r.headers


def test_saude_nao_e_limitada(limite_3):
    assert all(cliente.get("/saude").status_code == 200 for _ in range(10))


def test_redis_guarda_so_identificador_anonimizado(inferencia_falsa):
    r_falso = fakeredis.FakeRedis()
    gateway.limitador = LimitadorComReserva(LimitadorRedis(r_falso),
                                            LimitadorMemoria())
    assert _predict(_cab("aluno")).status_code == 200
    chaves = [k.decode() for k in r_falso.keys("*")]
    assert len(chaves) == 1
    assert chaves[0].startswith("ratelimit:api:")
    assert "aluno" not in chaves[0]
    assert 0 < r_falso.ttl(chaves[0]) <= 61  # expira sozinho


# ---------------------------------------------------------- limitador puro
@pytest.mark.parametrize("fabrica", [
    LimitadorMemoria,
    lambda: LimitadorRedis(fakeredis.FakeRedis()),
], ids=["memoria", "redis"])
def test_janela_fixa(fabrica):
    lim = fabrica()
    t0 = 16_667 * 60 + 20.0  # 20s dentro de uma janela de 60s
    res = [lim.registrar("c", 2, 60, agora=t0 + i) for i in range(3)]
    assert [r.permitido for r in res] == [True, True, False]
    assert [r.restantes for r in res] == [1, 0, 0]
    assert res[0].reset_em == 40
    # Outra chave tem contador proprio
    assert lim.registrar("d", 2, 60, agora=t0).permitido
    # Janela seguinte: contador zera
    assert lim.registrar("c", 2, 60, agora=t0 + 40).permitido


def test_redis_compartilhado_entre_replicas():
    """Dois gateways (dois limitadores) no mesmo Redis somam o mesmo contador."""
    servidor = fakeredis.FakeServer()
    gw1 = LimitadorRedis(fakeredis.FakeRedis(server=servidor))
    gw2 = LimitadorRedis(fakeredis.FakeRedis(server=servidor))
    t = 1_000_000.0
    assert gw1.registrar("c", 2, 60, agora=t).permitido
    assert gw2.registrar("c", 2, 60, agora=t).permitido
    assert not gw1.registrar("c", 2, 60, agora=t).permitido


def test_redis_fora_do_ar_cai_para_memoria(capsys):
    lim = criar_limitador("redis://127.0.0.1:1/0")  # porta sem ninguem
    assert isinstance(lim, LimitadorComReserva)
    r1 = lim.registrar("c", 1, 60)
    r2 = lim.registrar("c", 1, 60)
    assert r1.permitido and not r2.permitido  # limite segue valendo
    saida = capsys.readouterr().out
    assert saida.count("redis indisponivel") == 1  # pausa: nao re-tenta


def test_sem_redis_url_usa_memoria():
    assert isinstance(criar_limitador(""), LimitadorMemoria)


def test_erro_do_redis_e_redis_error():
    """Garante que a excecao capturada na reserva e a que o cliente lanca."""
    lim = LimitadorRedis(redis.Redis(host="127.0.0.1", port=1,
                                     socket_connect_timeout=0.1))
    with pytest.raises(redis.RedisError):
        lim.registrar("c", 1, 60)
