"""Configuracao comum dos testes do gateway (roda antes de importar app)."""
import os
import sys
from pathlib import Path

import pytest

os.environ.update(
    JWT_SEGREDO="segredo-de-teste-com-tamanho-suficiente-123",
    AUTH_USUARIO="aluno",
    AUTH_SENHA="senha-teste",
    JWT_EXPIRACAO_MIN="5",
    REDIS_URL="",  # testes usam o limitador em memoria (ou fakeredis)
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as gateway  # noqa: E402
from limitador import LimitadorMemoria  # noqa: E402


@pytest.fixture(autouse=True)
def limitador_zerado(monkeypatch):
    """Cada teste comeca com contadores zerados."""
    monkeypatch.setattr(gateway, "limitador", LimitadorMemoria())
