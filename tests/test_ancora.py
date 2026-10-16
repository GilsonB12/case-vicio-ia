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
    assert list(planilha.columns) == ["id", "disciplina_origem", "texto", "candidatos", "tema_id_gilson", "observacao"]
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


def test_carregar_ancora_manual_aceita_tema_zero_como_fora_da_arvore(arvore, tmp_path):
    caminho = tmp_path / "ancora_manual.csv"
    caminho.write_text('id,tema_id,observacao\nQ0001,5527,""\nQ0282,0,"nenhum tema serve"\n', encoding="utf-8-sig")
    df = ancora.carregar_ancora_manual(arvore, caminho)
    assert list(df["id"]) == ["Q0001", "Q0282"]
    assert list(df["tema_id"]) == [5527, ancora.TEMA_FORA]
    assert ancora.TEMA_FORA == 0


@pytest.mark.parametrize("tema", [4365, 99999])
def test_carregar_ancora_manual_rejeita_raiz_e_tema_inexistente(arvore, tmp_path, tema):
    caminho = tmp_path / "ancora_manual.csv"
    pd.DataFrame({"id": ["Q0001", "Q0002"], "tema_id": [0, tema]}).to_csv(caminho, index=False)
    with pytest.raises(ValueError, match=rf"não publicável.*\[{tema}\]"):
        ancora.carregar_ancora_manual(arvore, caminho)


def planilha_vazia(ids):
    return pd.DataFrame([{coluna: "" for coluna in ancora.COLUNAS} | {"id": i} for i in ids])


def test_rodar_ancora_nao_sobrescreve_planilha_rotulada(tmp_path):
    saida = tmp_path / "ancora_para_rotular.csv"
    planilha = planilha_vazia(["Q0001", "Q0002"])
    planilha.loc[1, "tema_id_gilson"] = "5527"
    planilha.to_csv(saida, index=False, encoding="utf-8-sig")
    antes = saida.read_bytes()
    with pytest.raises(FileExistsError, match="já tem rótulos"):
        ancora.rodar_ancora(caminho_candidatos=tmp_path / "candidatos_questoes_p1.jsonl", saida=saida)
    assert saida.read_bytes() == antes


def test_rodar_ancora_regrava_planilha_sem_rotulos_com_bom(tmp_path, questoes):
    from classificador.dados import escrever_jsonl

    candidatos = tmp_path / "candidatos_questoes_p1.jsonl"
    escrever_jsonl(candidatos, [{"id": i, "candidatos": [{"tema_id": 5527, "origem": "tema", "similaridade": 0.5}]}
                                for i in questoes["id"]])
    saida = tmp_path / "ancora_para_rotular.csv"
    planilha_vazia(["Q0001"]).to_csv(saida, index=False, sep=";", encoding="utf-8-sig")
    ancora.rodar_ancora(caminho_candidatos=candidatos, saida=saida)
    assert saida.read_bytes().startswith("﻿".encode("utf-8"))
    assert len(pd.read_csv(saida, encoding="utf-8-sig")) == 40


def test_carregar_ancora_manual_aceita_ponto_e_virgula_e_bom(arvore, tmp_path):
    caminho = tmp_path / "ancora_manual.csv"
    caminho.write_text("id;tema_id;observacao\nQ0001;5527;decisão conjunta\n", encoding="utf-8-sig")
    df = ancora.carregar_ancora_manual(arvore, caminho)
    assert list(df["id"]) == ["Q0001"]
    assert list(df["tema_id"]) == [5527]


def test_carregar_ancora_manual_acusa_tema_em_branco(arvore, tmp_path):
    caminho = tmp_path / "ancora_manual.csv"
    caminho.write_text("id,tema_id\nQ0001,5527\nQ0002,\nQ0003, \n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"em branco.*Q0002.*Q0003"):
        ancora.carregar_ancora_manual(arvore, caminho)


def test_carregar_ancora_manual_sem_coluna_tema_id_lista_as_colunas(arvore, tmp_path):
    caminho = tmp_path / "ancora_manual.csv"
    caminho.write_text("id,tema\nQ0001,5527\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"tema_id.*'id', 'tema'"):
        ancora.carregar_ancora_manual(arvore, caminho)
