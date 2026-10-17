import logging
from dataclasses import replace

import pytest

from classificador import pipeline


def test_tudo_roda_as_etapas_na_ordem(monkeypatch, tmp_path):
    chamadas = []
    etapas = [(nome, (lambda n=nome: chamadas.append(n))) for nome, _ in pipeline.ETAPAS_TUDO]
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("", encoding="utf-8")
    monkeypatch.setattr(pipeline, "caminho_corpus", lambda: corpus)
    pipeline.rodar_tudo(etapas)
    assert chamadas == [
        "candidatos p1 questoes",
        "ancora",
        "candidatos p2 questoes",
        "candidatos p2 corpus",
        "votos questoes",
        "reparo questoes",
        "votos corpus",
        "reparo corpus",
        "vizinhanca questoes",
        "vizinhanca corpus",
        "calibrar",
        "decidir",
        "publicar",
    ]


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


@pytest.fixture
def caminhos_temporarios(monkeypatch, tmp_path):
    intermediarios = tmp_path / "intermediarios"
    intermediarios.mkdir()
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("", encoding="utf-8")
    caminhos = replace(pipeline.CAMINHOS, intermediarios=intermediarios, corpus=corpus,
                       ancora_planilha=tmp_path / "ancora_para_rotular.csv")
    monkeypatch.setattr(pipeline, "CAMINHOS", caminhos)
    return caminhos


def test_tudo_sem_recalcular_pula_etapas_com_saida_existente(monkeypatch, caminhos_temporarios, caplog):
    (caminhos_temporarios.intermediarios / "candidatos_questoes_p1.jsonl").write_text("", encoding="utf-8")
    (caminhos_temporarios.intermediarios / "vizinhanca_questoes.jsonl").write_text("", encoding="utf-8")
    chamadas = []
    monkeypatch.setattr(pipeline.candidatos, "rodar_candidatos",
                        lambda alvo, passada, *a, **k: chamadas.append(f"candidatos p{passada} {alvo}"))
    monkeypatch.setattr(pipeline.vizinhanca, "rodar_vizinhanca", lambda alvo, *a, **k: chamadas.append(f"vizinhanca {alvo}"))
    monkeypatch.setattr(pipeline.ArvoreTemas, "carregar", classmethod(lambda cls: None))
    monkeypatch.setattr(pipeline, "criar_embeddings", lambda: None)
    etapas = [(nome, funcao) for nome, funcao in pipeline.ETAPAS_TUDO if nome.startswith(("candidatos", "vizinhanca"))]
    with caplog.at_level(logging.INFO, logger="classificador.pipeline"):
        pipeline.rodar_tudo(etapas)
    assert chamadas == ["candidatos p2 questoes", "candidatos p2 corpus", "vizinhanca corpus"]
    assert sum("reaproveitando" in r.getMessage() for r in caplog.records) == 2
    chamadas.clear()
    pipeline.rodar_tudo(etapas, recalcular=True)
    assert chamadas == ["candidatos p1 questoes", "candidatos p2 questoes", "candidatos p2 corpus",
                        "vizinhanca questoes", "vizinhanca corpus"]


def test_main_tudo_repassa_recalcular(monkeypatch):
    recebido = []
    monkeypatch.setattr(pipeline, "rodar_tudo", lambda recalcular=False: recebido.append(recalcular))
    pipeline.main(["tudo"])
    pipeline.main(["tudo", "--recalcular"])
    assert recebido == [False, True]


def test_etapa_ancora_pula_planilha_existente(monkeypatch, caminhos_temporarios, caplog):
    chamadas = []
    monkeypatch.setattr(pipeline.ancora, "rodar_ancora", lambda **k: chamadas.append(k))
    caminhos_temporarios.ancora_planilha.write_text("id\n", encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="classificador.pipeline"):
        pipeline.etapa_ancora()
    assert chamadas == []
    assert any("já existe" in r.getMessage() for r in caplog.records)
    pipeline.etapa_ancora(pular_se_existir=False)
    assert chamadas == [{"saida": caminhos_temporarios.ancora_planilha}]


def test_votos_sem_candidatos_da_passada_2_pede_para_gerar(caminhos_temporarios):
    with pytest.raises(FileNotFoundError, match=r"classificar candidatos --alvo corpus --passada 2"):
        pipeline.etapa_votos("corpus")


def test_publicar_mostra_intervalo_com_duas_casas(monkeypatch, caminhos_temporarios, capsys):
    import json

    from classificador.dados import escrever_jsonl

    escrever_jsonl(caminhos_temporarios.intermediarios / "decisoes_questoes.jsonl", [{"decisao": "publicar"}])
    resumo = {"precisao_prevista": 0.9712, "precisao_intervalo": [0.951234, 0.98765], "cobertura": 0.5, "cobertura_intervalo": [0.49, 0.51]}
    (caminhos_temporarios.intermediarios / "calibracao_resumo.json").write_text(json.dumps(resumo), encoding="utf-8")
    monkeypatch.setattr(pipeline.ArvoreTemas, "carregar", classmethod(lambda cls: None))
    monkeypatch.setattr(pipeline, "carregar_questoes", lambda: {"id": []})
    monkeypatch.setattr(pipeline.saida, "escrever_publicacao", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.calibracao, "escrever_previsao", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.calibracao, "montar_texto_previsao", lambda resumo: "")
    pipeline.etapa_publicar()
    assert "precisão 0.97 [0.95, 0.99], cobertura 0.50" in capsys.readouterr().out


@pytest.fixture
def caminhos_de_custos(monkeypatch, tmp_path):
    caminhos = replace(pipeline.CAMINHOS, intermediarios=tmp_path / "intermediarios", custos=tmp_path / "custos",
                       publicacao=tmp_path / "publicacao.csv")
    monkeypatch.setattr(pipeline, "CAMINHOS", caminhos)
    return caminhos


def test_custos_sem_livro_avisa_e_nao_falha(caminhos_de_custos, capsys):
    pipeline.main(["custos"])
    assert "nenhum registro" in capsys.readouterr().out.lower()
    assert not (caminhos_de_custos.custos / "custos_resumo.json").exists()


def test_custos_resume_o_livro_e_compara_com_o_painel(caminhos_de_custos, capsys):
    import json

    from classificador.custos import LivroRazao

    uso = {"tokens_entrada": 1000, "tokens_saida": 500, "tokens_raciocinio": 0,
           "tokens_cache_leitura": 0, "tokens_cache_escrita": 0}
    LivroRazao(caminhos_de_custos.custos / "chamadas.jsonl").registrar(
        etapa="votos", alvo="questoes", provedor="anthropic", modelo="claude-sonnet-5-5", origem="api", tentativa=1, uso=uso)
    pipeline.main(["custos", "--painel", "anthropic=0.01", "--painel", "openai=0"])
    saida = capsys.readouterr().out
    assert "Por etapa" in saida and "Painel" in saida
    resumo = json.loads((caminhos_de_custos.custos / "custos_resumo.json").read_text(encoding="utf-8"))
    assert resumo["total"]["custo_usd"] == pytest.approx(0.007)
    assert resumo["painel"]["anthropic"]["diferenca"] == pytest.approx(0.003)
    assert resumo["painel"]["openai"]["calculado"] == 0.0


def test_custos_recusa_painel_mal_escrito(caminhos_de_custos):
    with pytest.raises(SystemExit):
        pipeline.main(["custos", "--painel", "anthropic"])
    with pytest.raises(SystemExit):
        pipeline.main(["custos", "--painel", "anthropic=muito"])
