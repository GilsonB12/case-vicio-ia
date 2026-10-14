import pytest

from classificador import pipeline


def test_tudo_roda_as_etapas_na_ordem(monkeypatch, tmp_path):
    chamadas = []
    etapas = [(nome, (lambda n=nome: chamadas.append(n))) for nome, _ in pipeline.ETAPAS_TUDO]
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("", encoding="utf-8")
    monkeypatch.setattr(pipeline, "caminho_corpus", lambda: corpus)
    pipeline.rodar_tudo(etapas)
    assert chamadas == [nome for nome, _ in pipeline.ETAPAS_TUDO]
    assert chamadas[0].startswith("candidatos p1") and chamadas[-1] == "publicar"


def test_tudo_sem_corpus_falha_com_instrucao(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "caminho_corpus", lambda: tmp_path / "nao_existe.jsonl")
    with pytest.raises(FileNotFoundError, match="corpus"):
        pipeline.rodar_tudo([])


def test_main_despacha_subcomando(monkeypatch):
    recebido = {}
    monkeypatch.setattr(pipeline, "etapa_votos", lambda alvo, limite=None: recebido.update(alvo=alvo, limite=limite))
    pipeline.main(["votos", "--alvo", "corpus", "--limite", "5"])
    assert recebido == {"alvo": "corpus", "limite": 5}


def test_votos_verificar_testa_os_provedores_sem_votar(monkeypatch, capsys):
    monkeypatch.setattr(pipeline.llm, "verificar_provedores", lambda: {"openai": "ok", "anthropic": "sem ANTHROPIC_API_KEY"})
    monkeypatch.setattr(pipeline, "etapa_votos", lambda *a, **k: pytest.fail("não deveria votar"))
    pipeline.main(["votos", "--verificar"])
    assert capsys.readouterr().out.splitlines() == ["openai: ok", "anthropic: sem ANTHROPIC_API_KEY"]
