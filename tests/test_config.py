from pathlib import Path

from classificador import config


def test_caminhos_apontam_para_dentro_do_repositorio():
    raiz = Path(__file__).resolve().parents[1]
    assert config.CAMINHOS.questoes == raiz / "anexos" / "questoes.jsonl"
    assert config.CAMINHOS.temas == raiz / "anexos" / "temas.csv"
    assert config.CAMINHOS.intermediarios == raiz / "data" / "intermediarios"
    assert config.CAMINHOS.cache == raiz / "data" / "cache"
    assert config.CAMINHOS.publicacao == raiz / "publicacao.csv"


def test_ler_env_devolve_padrao(monkeypatch):
    monkeypatch.delenv("VARIAVEL_INEXISTENTE", raising=False)
    assert config.ler_env("VARIAVEL_INEXISTENTE", "x") == "x"
    monkeypatch.setenv("VARIAVEL_INEXISTENTE", "y")
    assert config.ler_env("VARIAVEL_INEXISTENTE", "x") == "y"
