import pytest

from classificador import saida
from classificador.arvore import ArvoreTemas


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def decisoes_validas():
    return [
        {"id": "Q0001", "decisao": "publicar", "tema_central_id": 5527, "extras_ids": [5524], "confianca": 0.9, "motivo": "", "regra": 2},
        {"id": "Q0002", "decisao": "revisar", "tema_central_id": 5159, "extras_ids": [], "confianca": 0.55, "motivo": "dúvida", "regra": 4},
        {"id": "Q0003", "decisao": "fora", "tema_central_id": None, "extras_ids": [], "confianca": None, "motivo": "tributário", "regra": 1},
    ]


def test_montar_publicacao_formata_tudo_como_texto():
    df = saida.montar_publicacao(decisoes_validas())
    assert list(df.columns) == saida.COLUNAS
    assert df.loc[0].tolist() == ["Q0001", "publicar", "5527", "5524", "0.90", ""]
    assert df.loc[2].tolist() == ["Q0003", "fora", "", "", "", "tributário"]


def test_validacao_aceita_decisoes_validas(arvore):
    df = saida.montar_publicacao(decisoes_validas())
    assert saida.validar_publicacao(df, ["Q0001", "Q0002", "Q0003"], arvore) == []


@pytest.mark.parametrize("alteracao, trecho", [
    ({"id": "Q0001"}, "repetid"),
    ({"decisao": "talvez"}, "decisao"),
    ({"tema_central_id": None}, "tema_central_id"),
    ({"tema_central_id": 6724}, "publicável"),
    ({"tema_central_id": 5062}, "publicável"),
    ({"confianca": 1.5}, "confianca"),
    ({"extras_ids": [5159, 5159]}, "extras"),
    ({"extras_ids": [5159]}, "extras"),
])
def test_validacao_acusa_erros(arvore, alteracao, trecho):
    decisoes = decisoes_validas()
    decisoes[1].update(alteracao)
    df = saida.montar_publicacao(decisoes)
    erros = saida.validar_publicacao(df, ["Q0001", "Q0002", "Q0003"], arvore)
    assert erros and any(trecho in e for e in erros)


def test_validacao_exige_motivo_em_revisar_e_fora_e_ids_completos(arvore):
    decisoes = decisoes_validas()
    decisoes[1]["motivo"] = ""
    df = saida.montar_publicacao(decisoes)
    erros = saida.validar_publicacao(df, ["Q0001", "Q0002", "Q0003", "Q0004"], arvore)
    assert any("motivo" in e for e in erros)
    assert any("Q0004" in e for e in erros)


def test_escrever_e_ler(arvore, tmp_path):
    caminho = tmp_path / "publicacao.csv"
    saida.escrever_publicacao(decisoes_validas(), ["Q0001", "Q0002", "Q0003"], arvore, caminho)
    df = saida.ler_publicacao(caminho)
    assert df.loc[0, "tema_central_id"] == "5527"
    assert df.loc[2, "tema_central_id"] == ""
    assert caminho.read_text(encoding="utf-8").splitlines()[0] == "id,decisao,tema_central_id,extras_ids,confianca,motivo"


def test_escrever_recusa_invalido(arvore, tmp_path):
    decisoes = decisoes_validas()
    decisoes[0]["tema_central_id"] = 6724
    with pytest.raises(ValueError, match="publicável"):
        saida.escrever_publicacao(decisoes, ["Q0001", "Q0002", "Q0003"], arvore, tmp_path / "p.csv")
