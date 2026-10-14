import pandas as pd
import pytest

from classificador import ancora
from classificador.arvore import ArvoreTemas
from classificador.dados import carregar_questoes


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


@pytest.fixture(scope="module")
def questoes():
    return carregar_questoes()


def test_sorteio_tem_40_e_e_deterministico(questoes):
    a = ancora.sortear_ancora(questoes)
    b = ancora.sortear_ancora(questoes)
    assert len(a) == 40
    assert list(a["id"]) == list(b["id"])
    assert a["id"].is_unique
    assert list(a["id"]) == sorted(a["id"])


def test_sorteio_e_proporcional_por_disciplina(questoes):
    a = ancora.sortear_ancora(questoes)
    contagem = a["disciplina_origem"].value_counts()
    assert 14 <= contagem["Processo Penal"] <= 16
    assert 13 <= contagem["Direito Penal"] <= 15
    assert contagem.sum() == 40


def test_planilha_tem_colunas_e_candidatos_formatados(questoes, arvore):
    candidatos = {i: [{"tema_id": 5527, "origem": "tema", "similaridade": 0.5}] for i in questoes["id"]}
    planilha = ancora.gerar_planilha_ancora(questoes, candidatos, arvore)
    assert list(planilha.columns) == ["id", "disciplina_origem", "texto", "candidatos", "tema_id_gilson", "tema_id_segunda_passagem", "observacao"]
    assert len(planilha) == 40
    assert planilha.loc[0, "candidatos"].startswith("5527 | Processo Penal > Procedimento do Tribunal do Júri >")
    assert (planilha["tema_id_gilson"] == "").all()


def test_carregar_ancora_manual_valida_temas(arvore, tmp_path):
    caminho = tmp_path / "ancora_manual.csv"
    pd.DataFrame({"id": ["Q0001"], "tema_id": [5527]}).to_csv(caminho, index=False)
    df = ancora.carregar_ancora_manual(arvore, caminho)
    assert list(df["id"]) == ["Q0001"]
    pd.DataFrame({"id": ["Q0001"], "tema_id": [6724]}).to_csv(caminho, index=False)
    with pytest.raises(ValueError, match="6724"):
        ancora.carregar_ancora_manual(arvore, caminho)
