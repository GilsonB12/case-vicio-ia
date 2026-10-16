import logging
import re
from dataclasses import asdict

import pandas as pd
import pytest

from classificador import calibracao as cal
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato
from classificador.dados import escrever_jsonl
from classificador.decisao import Limiares
from classificador.llm import VotoModelo


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def v(tema, conf):
    return VotoModelo(tema_central_id=tema, extras_ids=[], disciplina="Processo Penal", confianca=conf, justificativa="")


def entrada(id_, tema_a, tema_b, conf, verdadeiro):
    return cal.Entrada(id_, v(tema_a, conf), v(tema_b, conf), None, [Candidato(tema_a, "tema", 0.5)], verdadeiro)


def corpus_sintetico(n_alta=10):
    """n_alta questões a 0.95, sempre certas; 10 a 0.65, certas na metade."""
    entradas = [entrada(f"C{i}", 5527, 5527, 0.95, 5527) for i in range(n_alta)]
    for j in range(10):
        verdadeiro = 5527 if j % 2 == 0 else 5159
        entradas.append(entrada(f"C{n_alta + j}", 5527, 5527, 0.65, verdadeiro))
    return entradas


def questoes_sinteticas():
    return [entrada(f"Q{i}", 5527, 5527, 0.95 if i < 4 else 0.65, None) for i in range(8)]


def test_faixa_de():
    assert cal.faixa_de(None) == "sem"
    assert cal.faixa_de(0.0) == "0.0-0.6"
    assert cal.faixa_de(0.6) == "0.6-0.7"
    assert cal.faixa_de(0.9) == "0.9-1.0"
    assert cal.faixa_de(1.0) == "0.9-1.0"


def test_faixa_de_fora_do_intervalo():
    assert cal.faixa_de(-0.1) == "0.0-0.6"
    assert cal.faixa_de(1.5) == "0.9-1.0"


def test_tabela_faixas_mede_precisao_no_corpus(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    entradas = corpus_sintetico()
    avaliacao = cal.avaliar(cal.decidir_todas(entradas, arvore, limiares), entradas, arvore)
    tabela = cal.tabela_faixas(avaliacao).set_index(["regra", "faixa"])
    assert tabela.loc[(2, "0.9-1.0"), "precisao"] == pytest.approx(1.0)
    assert tabela.loc[(2, "0.6-0.7"), "precisao"] == pytest.approx(0.5)
    assert tabela.loc[(2, "0.6-0.7"), "n"] == 10


def test_precisao_reponderada_usa_a_distribuicao_das_questoes(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    corpus = corpus_sintetico()
    aval_c = cal.avaliar(cal.decidir_todas(corpus, arvore, limiares), corpus, arvore)
    questoes = questoes_sinteticas()
    aval_q = cal.avaliar(cal.decidir_todas(questoes, arvore, limiares), questoes, arvore)
    tabela = cal.tabela_faixas(aval_c)
    # células 10/10 e 5/10 com Jeffreys: 10.5/11 e 5.5/11; 4 publicadas em cada -> 8/11
    assert cal.precisao_reponderada(tabela, aval_q) == pytest.approx(8 / 11)


def test_celula_pequena_recua_para_a_faixa():
    tabela = pd.DataFrame([
        {"regra": 2, "faixa": "0.9-1.0", "n": 20, "acertos": 18},
        {"regra": 3, "faixa": "0.9-1.0", "n": 3, "acertos": 0},
        {"regra": 2, "faixa": "0.8-0.9", "n": 2, "acertos": 2},
    ])
    tabela["precisao"] = tabela["acertos"] / tabela["n"]

    def publicada(regra, faixa):
        return pd.DataFrame([{"decisao": "publicar", "regra": regra, "faixa": faixa}])

    # célula com 20: usa a própria célula, 18/20 suavizado
    assert cal.precisao_reponderada(tabela, publicada(2, "0.9-1.0")) == pytest.approx(18.5 / 21)
    # célula com 3 < 5: usa a faixa 0.9-1.0 somada nas regras, 18/23 suavizado
    assert cal.precisao_reponderada(tabela, publicada(3, "0.9-1.0")) == pytest.approx(18.5 / 24)
    # célula e faixa 0.8-0.9 com 2 < 5: usa o corpus inteiro, 20/25 suavizado
    assert cal.precisao_reponderada(tabela, publicada(2, "0.8-0.9")) == pytest.approx(20.5 / 26)


def test_bootstrap_devolve_intervalo_que_contem_a_estimativa(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    corpus = corpus_sintetico()
    aval_c = cal.avaliar(cal.decidir_todas(corpus, arvore, limiares), corpus, arvore)
    questoes = questoes_sinteticas()
    aval_q = cal.avaliar(cal.decidir_todas(questoes, arvore, limiares), questoes, arvore)
    inferior, superior = cal.bootstrap_precisao(aval_c, aval_q, repeticoes=100)
    assert 0.0 <= inferior <= 8 / 11 <= superior <= 1.0


def test_intervalo_nao_colapsa_em_celula_pequena_toda_certa(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    corpus = [entrada(f"C{i}", 5527, 5527, 0.95, 5527) for i in range(3)]
    aval_c = cal.avaliar(cal.decidir_todas(corpus, arvore, limiares), corpus, arvore)
    questoes = questoes_sinteticas()[:4]
    aval_q = cal.avaliar(cal.decidir_todas(questoes, arvore, limiares), questoes, arvore)
    inferior, superior = cal.bootstrap_precisao(aval_c, aval_q, repeticoes=1000)
    # 3/3 certas: a reamostragem dava [1.0, 1.0]; a posterior Beta(3.5, 0.5) não colapsa
    assert 0.0 < inferior < 0.9
    assert inferior < 3.5 / 4 <= superior <= 1.0


def test_varredura_e_escolha_preferem_cobertura_com_precisao(arvore):
    varredura = cal.varrer_limiares(corpus_sintetico(n_alta=80), questoes_sinteticas(), arvore, grade=[0.6, 0.9], repeticoes=50)
    assert set(varredura.columns) >= {"publicar", "pai", "cobertura", "precisao_prevista", "limite_inferior", "limite_superior"}
    assert len(varredura) == 4
    escolhido, degrau = cal.escolher_limiares(varredura, alvo=0.97, piso=0.95)
    assert escolhido.publicar == pytest.approx(0.9)
    assert degrau == 0
    linha = varredura[(varredura.publicar == 0.9) & (varredura.pai == 0.9)].iloc[0]
    assert linha["cobertura"] == pytest.approx(0.5)
    assert linha["precisao_prevista"] == pytest.approx(80.5 / 81)
    assert linha["limite_inferior"] >= 0.95
    # publicar=0.6 cobre tudo, mas a célula 5/10 derruba a prevista abaixo do alvo
    baixa = varredura[(varredura.publicar == 0.6) & (varredura.pai == 0.9)].iloc[0]
    assert baixa["cobertura"] == pytest.approx(1.0)
    assert baixa["precisao_prevista"] == pytest.approx((80.5 / 81 + 5.5 / 11) / 2)
    assert baixa["precisao_prevista"] < 0.97


def test_escolher_limiares_sem_candidato_pega_maior_limite_inferior():
    varredura = pd.DataFrame([
        {"publicar": 0.6, "pai": 0.6, "cobertura": 0.9, "precisao_prevista": 0.80, "limite_inferior": 0.70, "limite_superior": 0.9},
        {"publicar": 0.9, "pai": 0.9, "cobertura": 0.5, "precisao_prevista": 0.93, "limite_inferior": 0.88, "limite_superior": 0.98},
    ])
    limiares, degrau = cal.escolher_limiares(varredura)
    assert limiares.publicar == pytest.approx(0.9)
    assert degrau == 3


def test_escolher_limiares_desempata_pelo_limite_inferior():
    varredura = pd.DataFrame([
        {"publicar": 0.8, "pai": 0.7, "cobertura": 0.6, "precisao_prevista": 0.98, "limite_inferior": 0.955, "limite_superior": 0.99},
        {"publicar": 0.8, "pai": 0.8, "cobertura": 0.6, "precisao_prevista": 0.98, "limite_inferior": 0.965, "limite_superior": 0.99},
    ])
    limiares, degrau = cal.escolher_limiares(varredura)
    assert limiares.pai == pytest.approx(0.8)
    assert degrau == 0


def test_escada_de_selecao_usa_o_degrau_certo(caplog):
    def linha(publicar, prevista, inferior, cobertura):
        return {"publicar": publicar, "pai": 0.7, "cobertura": cobertura, "precisao_prevista": prevista,
                "limite_inferior": inferior, "limite_superior": 0.99}

    casos = [
        # degrau 0: meta e piso; entre os pares aptos, o de maior cobertura
        ([linha(0.90, 0.98, 0.96, 0.4), linha(0.85, 0.98, 0.955, 0.6), linha(0.60, 0.90, 0.80, 0.9)], 0.85, 0),
        # degrau 1: só o piso; entre os pares com limite inferior >= 0.95, o de maior cobertura
        ([linha(0.80, 0.96, 0.951, 0.5), linha(0.90, 0.965, 0.96, 0.3), linha(0.60, 0.98, 0.90, 0.7)], 0.80, 1),
        # degrau 2: só a meta; entre os pares com prevista >= 0.97, o de maior limite inferior
        ([linha(0.75, 0.975, 0.93, 0.6), linha(0.90, 0.98, 0.94, 0.3), linha(0.60, 0.90, 0.945, 0.8)], 0.90, 2),
        # degrau 3: nenhuma das duas; o de maior limite inferior
        ([linha(0.60, 0.90, 0.85, 0.7), linha(0.80, 0.92, 0.88, 0.4)], 0.80, 3),
    ]
    for linhas, publicar_esperado, degrau_esperado in casos:
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="classificador.calibracao"):
            limiares, degrau = cal.escolher_limiares(pd.DataFrame(linhas), alvo=0.97, piso=0.95)
        assert limiares.publicar == pytest.approx(publicar_esperado)
        assert degrau == degrau_esperado
        assert bool(caplog.records) == (degrau_esperado > 0)


def test_comparar_ancora_e_ajustar_intervalo(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    questoes = questoes_sinteticas()
    aval_q = cal.avaliar(cal.decidir_todas(questoes, arvore, limiares), questoes, arvore)
    ancora = pd.DataFrame({"id": ["Q0", "Q1", "Q2"], "tema_id": [5527, 5524, 5159]})
    corpus = corpus_sintetico()
    tabela = cal.tabela_faixas(cal.avaliar(cal.decidir_todas(corpus, arvore, limiares), corpus, arvore))
    resultado = cal.comparar_ancora(aval_q, ancora, arvore, tabela)
    assert resultado["n_publicadas_na_ancora"] == 3
    assert resultado["acertos"] == 2
    assert resultado["precisao_observada"] == pytest.approx(2 / 3)
    assert cal.ajustar_intervalo(0.9, 0.99, 0.95) == (0.9, 0.99)
    assert cal.ajustar_intervalo(0.9, 0.99, 0.8) == (0.8, 0.99)
    assert cal.ajustar_intervalo(0.9, 0.95, None) == (0.9, 0.95)


def test_comparar_ancora_com_tema_fora_da_arvore_conta_como_erro(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    questoes = questoes_sinteticas()
    aval_q = cal.avaliar(cal.decidir_todas(questoes, arvore, limiares), questoes, arvore)
    # Q0 publicada no próprio tema, Q1 no filho do tema da âncora (5527 é filho de 5524), Q2 com âncora fora da árvore.
    ancora = pd.DataFrame({"id": ["Q0", "Q1", "Q2"], "tema_id": [5527, 5524, 0]})
    corpus = corpus_sintetico()
    tabela = cal.tabela_faixas(cal.avaliar(cal.decidir_todas(corpus, arvore, limiares), corpus, arvore))
    resultado = cal.comparar_ancora(aval_q, ancora, arvore, tabela)
    assert resultado["n_publicadas_na_ancora"] == 3
    assert resultado["acertos"] == 2
    assert resultado["precisao_observada"] == pytest.approx(2 / 3)


def test_escrever_previsao_segue_o_formato(tmp_path):
    caminho = cal.escrever_previsao(tmp_path / "previsao.txt", 0.971, (0.95, 0.99), 0.6, (0.59, 0.61), "explicação")
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    assert re.fullmatch(r"precisao_prevista: 0\.97\s+# fração das publicadas que estará certa", linhas[0])
    assert linhas[1] == "precisao_intervalo: 0.95-0.99"
    assert re.fullmatch(r"cobertura_prevista: 0\.60\s+# fração das questões que você publicou", linhas[2])
    assert linhas[3] == "cobertura_intervalo: 0.59-0.61"
    assert linhas[5] == "explicação"


def test_rodar_calibracao_sem_votos_do_corpus_falha_com_mensagem_clara(arvore, tmp_path):
    with pytest.raises(FileNotFoundError, match=r"votos_llm_corpus\.jsonl não existe; rode os votos de 'corpus'"):
        cal.rodar_calibracao(arvore, pasta=tmp_path, caminho_ancora=tmp_path / "ancora_manual.csv")


def resumo_para_texto(**mudancas):
    resumo = {
        "n_corpus": 40, "n_questoes": 10, "n_publicadas": 6, "repeticoes_final": 200,
        "limiares": {"publicar": 0.7, "pai": 0.5, "contradicao": 0.6},
        "ancora": None, "n_ancora": 0, "intervalo_alargado": False, "alvo_atingido": True, "varredura_atingiu_alvo": True,
        "degrau": 0, "intervalo_bruto": [0.95, 0.99], "precisao_intervalo": [0.95, 0.99],
    }
    resumo.update(mudancas)
    return resumo


def test_texto_previsao_diz_quando_alvo_nao_foi_atingido():
    texto = cal.montar_texto_previsao(resumo_para_texto(alvo_atingido=False, varredura_atingiu_alvo=False, degrau=3))
    assert "nenhum par de limiares" in texto
    assert "pelo menos 0.97" not in texto
    assert "nenhum par de limiares atingiu ao mesmo tempo a meta de precisão prevista 0.97 e o piso de 0.95" in texto
    assert "Usamos o último critério: nenhum par cumpriu sequer uma das duas condições" in texto
    assert "o par escolhido não cumpre ao mesmo tempo as duas condições" in texto
    assert "abaixo da meta" not in texto
    assert "0.70 no tema, 0.50 no pai" in texto
    # a varredura achou par apto, mas os números finais não cumprem: não diz que nenhum par atingiu
    texto = cal.montar_texto_previsao(resumo_para_texto(alvo_atingido=False))
    assert "nenhum par de limiares" not in texto
    assert "o par escolhido não cumpre ao mesmo tempo a meta de precisão prevista 0.97 e o piso de 0.95" in texto
    texto = cal.montar_texto_previsao(resumo_para_texto())
    assert "nenhum par de limiares" not in texto
    assert "não cumpre" not in texto
    assert "pelo menos 0.97 e limite inferior do intervalo de pelo menos 0.95" in texto
    assert "primeiro critério da escada de seleção" in texto
    assert not re.search(r"\d,\d", texto)


def test_texto_previsao_diz_o_degrau_usado():
    texto = cal.montar_texto_previsao(resumo_para_texto(alvo_atingido=False, varredura_atingiu_alvo=False, degrau=1))
    assert "Usamos o segundo critério: entre os pares com limite inferior de pelo menos 0.95, o de maior cobertura" in texto
    texto = cal.montar_texto_previsao(resumo_para_texto(alvo_atingido=False, varredura_atingiu_alvo=False, degrau=2))
    assert "Usamos o terceiro critério: nenhum par teve limite inferior de pelo menos 0.95" in texto
    assert "o par escolhido não cumpre ao mesmo tempo as duas condições" in texto
    # degrau 2 na varredura, mas o intervalo final de 1000 sorteios cumpre o piso
    texto = cal.montar_texto_previsao(resumo_para_texto(varredura_atingiu_alvo=False, degrau=2))
    assert "Com os números finais, de 200 sorteios, o par escolhido cumpre as duas condições." in texto
    assert not re.search(r"\d,\d", texto)


def test_texto_previsao_descreve_o_metodo():
    texto = cal.montar_texto_previsao(resumo_para_texto())
    assert "suavização de Jeffreys" in texto
    assert "menos de 5 questões do corpus" in texto
    assert "posterior Beta" in texto
    assert "200 sorteios" in texto
    assert "bootstrap" not in texto
    assert "corrige só a diferença na mistura de regras de decisão e faixas de confiança" in texto
    assert "a única checagem dessa suposição é a âncora manual" in texto
    assert "Para corrigir isso" not in texto
    assert "mesmo corpus usado para estimar a precisão" in texto


def test_texto_previsao_distingue_ancora_ausente_de_ancora_sem_publicadas():
    texto = cal.montar_texto_previsao(resumo_para_texto())
    assert "Não houve âncora manual disponível" in texto
    sem_publicadas = {"n_publicadas_na_ancora": 0, "acertos": 0, "precisao_observada": None, "precisao_prevista_para_elas": None}
    texto = cal.montar_texto_previsao(resumo_para_texto(ancora=sem_publicadas, n_ancora=38))
    assert "não tinha nenhuma questão publicada para comparar" in texto
    assert "âncora manual de 38 questões" in texto
    assert "Não houve âncora manual disponível" not in texto


def test_texto_previsao_mostra_o_limite_inferior_depois_de_alargar():
    com_publicadas = {"n_publicadas_na_ancora": 5, "acertos": 3, "precisao_observada": 0.6, "precisao_prevista_para_elas": 0.97}
    texto = cal.montar_texto_previsao(resumo_para_texto(
        ancora=com_publicadas, n_ancora=38, intervalo_alargado=True,
        intervalo_bruto=[0.95, 0.99], precisao_intervalo=[0.6, 0.99],
    ))
    assert "das 5 questões publicadas que estavam na âncora de 38 rotuladas às cegas, 3 estavam certas" in texto
    assert "O intervalo foi alargado para conter a observação; depois do alargamento, o limite inferior é 0.60 (antes, 0.95)." in texto
    texto = cal.montar_texto_previsao(resumo_para_texto(ancora=com_publicadas | {"precisao_observada": 0.96}, n_ancora=38))
    assert "A observação cabe no intervalo." in texto
    assert "alargado" not in texto


def gravar_alvo(pasta, alvo, entradas):
    escrever_jsonl(pasta / f"votos_llm_{alvo}.jsonl",
                   [{"id": e.id, "openai": e.voto_a.model_dump(), "anthropic": e.voto_b.model_dump()} for e in entradas])
    escrever_jsonl(pasta / f"candidatos_{alvo}_p2.jsonl",
                   [{"id": e.id, "candidatos": [asdict(c) for c in e.candidatos]} for e in entradas])


@pytest.fixture
def pasta_calibracao(tmp_path, monkeypatch):
    corpus = corpus_sintetico(n_alta=80)
    gravar_alvo(tmp_path, "corpus", corpus)
    gravar_alvo(tmp_path, "questoes", questoes_sinteticas())
    tabela_corpus = pd.DataFrame({"id": [e.id for e in corpus], "tema_id": [e.verdadeiro for e in corpus]})
    monkeypatch.setattr(cal, "carregar_corpus", lambda: tabela_corpus)
    return tmp_path


def test_rodar_calibracao_grava_arquivos_e_resumo(arvore, pasta_calibracao):
    resumo = cal.rodar_calibracao(arvore, pasta=pasta_calibracao, caminho_ancora=pasta_calibracao / "ausente.csv",
                                  repeticoes_varredura=50, repeticoes_final=200)
    for nome in ["calibracao_varredura.csv", "calibracao_faixas.csv", "avaliacao_corpus.csv", "limiares.json", "calibracao_resumo.json"]:
        assert (pasta_calibracao / nome).exists()
    assert resumo["limiares"]["publicar"] >= 0.7
    assert resumo["cobertura"] == pytest.approx(0.5)
    assert resumo["precisao_prevista"] == pytest.approx(80.5 / 81)
    assert resumo["intervalo_bruto"][0] >= 0.95
    assert resumo["varredura_atingiu_alvo"] is True
    assert resumo["degrau"] == 0
    assert resumo["alvo_atingido"] is True
    assert resumo["ancora"] is None
    assert resumo["n_ancora"] == 0


def test_alvo_atingido_vem_dos_numeros_finais(arvore, pasta_calibracao, monkeypatch):
    original = cal.bootstrap_precisao

    def bootstrap_final_largo(aval_c, aval_q, repeticoes, semente=42):
        if repeticoes == 200:
            return 0.90, 0.99
        return original(aval_c, aval_q, repeticoes, semente)

    monkeypatch.setattr(cal, "bootstrap_precisao", bootstrap_final_largo)
    resumo = cal.rodar_calibracao(arvore, pasta=pasta_calibracao, caminho_ancora=pasta_calibracao / "ausente.csv",
                                  repeticoes_varredura=50, repeticoes_final=200)
    assert resumo["varredura_atingiu_alvo"] is True
    assert resumo["intervalo_bruto"] == [0.90, 0.99]
    assert resumo["alvo_atingido"] is False


def test_rodar_calibracao_sem_questoes_tem_cobertura_zero(arvore, pasta_calibracao):
    gravar_alvo(pasta_calibracao, "questoes", [])
    resumo = cal.rodar_calibracao(arvore, pasta=pasta_calibracao, caminho_ancora=pasta_calibracao / "ausente.csv",
                                  repeticoes_varredura=10, repeticoes_final=10)
    assert resumo["n_questoes"] == 0
    assert resumo["cobertura"] == 0.0
    assert resumo["alvo_atingido"] is False
