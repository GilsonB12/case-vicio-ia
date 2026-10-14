import re

import pandas as pd
import pytest

from classificador import calibracao as cal
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato
from classificador.decisao import Limiares
from classificador.llm import VotoModelo


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def v(tema, conf):
    return VotoModelo(tema_central_id=tema, extras_ids=[], disciplina="Processo Penal", confianca=conf, justificativa="")


def entrada(id_, tema_a, tema_b, conf, verdadeiro):
    return cal.Entrada(id_, v(tema_a, conf), v(tema_b, conf), None, [Candidato(tema_a, "tema", 0.5)], verdadeiro)


def corpus_sintetico():
    """20 questões: confiança 0.95 sempre certa; 0.65 certa na metade."""
    entradas = []
    for i in range(10):
        entradas.append(entrada(f"C{i}", 5527, 5527, 0.95, 5527))
    for i in range(10, 20):
        verdadeiro = 5527 if i % 2 == 0 else 5159
        entradas.append(entrada(f"C{i}", 5527, 5527, 0.65, verdadeiro))
    return entradas


def questoes_sinteticas():
    return [entrada(f"Q{i}", 5527, 5527, 0.95 if i < 4 else 0.65, None) for i in range(8)]


def test_faixa_de():
    assert cal.faixa_de(None) == "sem"
    assert cal.faixa_de(0.0) == "0.0-0.6"
    assert cal.faixa_de(0.6) == "0.6-0.7"
    assert cal.faixa_de(0.9) == "0.9-1.0"
    assert cal.faixa_de(1.0) == "0.9-1.0"


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
    # 4 publicadas a 1.0 e 4 a 0.5 -> 0.75
    assert cal.precisao_reponderada(tabela, aval_q) == pytest.approx(0.75)


def test_bootstrap_devolve_intervalo_que_contem_a_estimativa(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    corpus = corpus_sintetico()
    aval_c = cal.avaliar(cal.decidir_todas(corpus, arvore, limiares), corpus, arvore)
    questoes = questoes_sinteticas()
    aval_q = cal.avaliar(cal.decidir_todas(questoes, arvore, limiares), questoes, arvore)
    inferior, superior = cal.bootstrap_precisao(aval_c, aval_q, repeticoes=100)
    assert 0.0 <= inferior <= 0.75 <= superior <= 1.0


def test_varredura_e_escolha_preferem_cobertura_com_precisao(arvore):
    varredura = cal.varrer_limiares(corpus_sintetico(), questoes_sinteticas(), arvore, grade=[0.6, 0.9], repeticoes=50)
    assert set(varredura.columns) >= {"publicar", "pai", "cobertura", "precisao_prevista", "limite_inferior", "limite_superior"}
    assert len(varredura) == 4
    escolhido = cal.escolher_limiares(varredura, alvo=0.97, piso=0.95)
    assert escolhido.publicar == pytest.approx(0.9)
    linha = varredura[(varredura.publicar == 0.9) & (varredura.pai == 0.9)].iloc[0]
    assert linha["cobertura"] == pytest.approx(0.5)
    assert linha["precisao_prevista"] == pytest.approx(1.0)


def test_escolher_limiares_sem_candidato_pega_maior_limite_inferior():
    varredura = pd.DataFrame([
        {"publicar": 0.6, "pai": 0.6, "cobertura": 0.9, "precisao_prevista": 0.80, "limite_inferior": 0.70, "limite_superior": 0.9},
        {"publicar": 0.9, "pai": 0.9, "cobertura": 0.5, "precisao_prevista": 0.93, "limite_inferior": 0.88, "limite_superior": 0.98},
    ])
    assert cal.escolher_limiares(varredura).publicar == pytest.approx(0.9)


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


def test_texto_previsao_diz_quando_alvo_nao_foi_atingido():
    resumo = {
        "n_corpus": 40, "n_questoes": 10, "n_publicadas": 6, "repeticoes_final": 200,
        "limiares": {"publicar": 0.7, "pai": 0.5, "contradicao": 0.6},
        "ancora": None, "intervalo_alargado": False, "alvo_atingido": False,
    }
    texto = cal.montar_texto_previsao(resumo)
    assert "nenhum par de limiares" in texto
    assert "pelo menos 0.97" not in texto
    assert "0.70 no tema, 0.50 no pai" in texto
    resumo["alvo_atingido"] = True
    texto = cal.montar_texto_previsao(resumo)
    assert "nenhum par de limiares" not in texto
    assert "pelo menos 0.97 e limite inferior do intervalo de pelo menos 0.95" in texto
    assert not re.search(r"\d,\d", texto)
