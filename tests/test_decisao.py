import pytest

from classificador import decisao as modulo
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato
from classificador.dados import escrever_jsonl, ler_jsonl
from classificador.decisao import Limiares, decidir
from classificador.llm import VotoModelo
from classificador.vizinhanca import VotoVizinhanca

L = Limiares(publicar=0.8, pai=0.7, contradicao=0.6)
CAND = [Candidato(5524, "tema", 0.7), Candidato(5527, "tema", 0.6), Candidato(5528, "tema", 0.5), Candidato(5159, "tema", 0.4)]


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def v(tema, conf=0.9, disciplina="Processo Penal", extras=()):
    return VotoModelo(tema_central_id=tema, extras_ids=list(extras), disciplina=disciplina, confianca=conf, justificativa="porque sim")


def viz(n1=None, p1=0.0, n2=None, p2=0.0):
    return VotoVizinhanca(n2, p2, n1, p1, [])


def d(a, b, vz=None, limiares=L, arvore=None):
    return decidir("Q1", a, b, vz, CAND, arvore, limiares)


def test_regra1_fora_quando_ambos_outra(arvore):
    r = d(v(None, 0.3, "Outra"), v(None, 0.2, "Outra"), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("fora", None, 1)
    assert r.motivo.startswith("fora das quatro disciplinas")
    assert r.confianca is None


def test_regra2_publica_quando_concordam(arvore):
    r = d(v(5527, 0.9, extras=[5528]), v(5527, 0.85, extras=[5524]), viz(5524, 0.9, 5527, 0.8), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("publicar", 5527, 2)
    assert r.confianca == pytest.approx(0.85)
    assert set(r.extras_ids) == {5528, 5524}
    assert r.motivo == ""


def test_regra5_revisa_quando_concordam_abaixo_do_limiar(arvore):
    r = d(v(5527, 0.9), v(5527, 0.7), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5527, 5)
    assert "limiar" in r.motivo


def test_regra5_revisa_quando_vizinhanca_contradiz_com_forca(arvore):
    forte = d(v(5527), v(5527), viz(5543, 0.7), arvore=arvore)
    assert (forte.decisao, forte.regra) == ("revisar", 5)
    assert "vizinhan" in forte.motivo
    fraca = d(v(5527), v(5527), viz(5543, 0.5), arvore=arvore)
    assert fraca.decisao == "publicar"


def test_regra3_publica_no_pai_quando_irmaos(arvore):
    r = d(v(5527, 0.8), v(5528, 0.75), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("publicar", 5524, 3)
    assert set(r.extras_ids) == {5527, 5528}
    assert r.confianca == pytest.approx(0.75)


def test_regra3_publica_no_pai_quando_pai_e_filho(arvore):
    r = d(v(5524, 0.9), v(5527, 0.8), arvore=arvore)
    assert (r.decisao, r.tema_central_id) == ("publicar", 5524)
    assert r.extras_ids == [5527]


def test_regra3_revisa_abaixo_do_limiar_do_pai(arvore):
    r = d(v(5527, 0.6), v(5528, 0.9), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5524, 3)


def test_regra4_sugere_pelo_ramo_da_vizinhanca(arvore):
    r = d(v(5527, 0.9), v(5159, 0.6), viz(5157, 0.8), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5159, 4)
    assert r.confianca == pytest.approx(0.6)
    assert "divergem" in r.motivo


def test_regra4_sem_vizinhanca_usa_maior_confianca_e_empate_vai_para_a(arvore):
    assert d(v(5527, 0.6), v(5159, 0.9), arvore=arvore).tema_central_id == 5159
    assert d(v(5527, 0.7), v(5159, 0.7), arvore=arvore).tema_central_id == 5527


def test_dois_temas_de_nivel1_diferentes_nunca_publicam_na_raiz(arvore):
    r = d(v(5543, 0.95), v(5590, 0.95), arvore=arvore)
    assert r.decisao == "revisar" and r.regra == 4
    assert r.tema_central_id in {5543, 5590}


def test_regra6_fora_quando_ambos_nenhum_nas_disciplinas(arvore):
    r = d(v(None, 0.4), v(None, 0.3, "Penal"), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("fora", None, 6)
    assert r.motivo.startswith("nenhum tema da árvore cobre o assunto")


def test_regra6_revisa_quando_um_outra_e_um_nenhum(arvore):
    r = d(v(None, 0.4, "Outra"), v(None, 0.3), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5524, 6)


def test_regra6_revisa_quando_so_um_nenhum(arvore):
    r = d(v(None, 0.4), v(5527, 0.7), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5527, 6)
    assert r.confianca == pytest.approx(0.7)


def test_regra7_um_modelo_falhou(arvore):
    r = d(v(5527, 0.9), None, arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5527, 7)
    assert r.motivo == "modelo sem resposta válida"


def test_regra7_nenhum_voto_usa_primeiro_candidato(arvore):
    r = d(None, None, arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra, r.confianca) == ("revisar", 5524, 7, None)


def test_extras_nao_incluem_central_inativo_nem_raiz(arvore):
    r = d(v(5527, extras=[5527, 5078, 5062, 5528]), v(5527), arvore=arvore)
    assert r.extras_ids == [5528]


def test_extras_canonicalizam_duplicados(arvore):
    r = d(v(5527, extras=[6724]), v(5527), arvore=arvore)
    assert r.extras_ids == [4704]


def test_regra4_extras_nao_recebem_o_tema_do_outro_ramo(arvore):
    r = d(v(5527, 0.9, extras=[5528]), v(5159, 0.6), arvore=arvore)
    assert (r.tema_central_id, r.regra) == (5527, 4)
    assert r.extras_ids == [5528]


def test_regra6_extras_unem_os_dois_votos(arvore):
    r = d(v(None, 0.4, extras=[5528]), v(5527, 0.7, extras=[5524]), arvore=arvore)
    assert (r.tema_central_id, r.regra) == (5527, 6)
    assert r.extras_ids == [5528, 5524]


def test_limiares_ida_e_volta():
    assert Limiares.de_dict(L.para_dict()) == L


def test_rodar_decisoes_grava(arvore, tmp_path):
    escrever_jsonl(tmp_path / "votos_llm_questoes.jsonl", [
        {"id": "Q1", "openai": v(5527).model_dump(), "anthropic": v(5527).model_dump()},
    ])
    escrever_jsonl(tmp_path / "candidatos_questoes_p2.jsonl", [
        {"id": "Q1", "candidatos": [{"tema_id": 5527, "origem": "tema", "similaridade": 0.5}]},
    ])
    saida = modulo.rodar_decisoes("questoes", arvore, L, pasta=tmp_path)
    linhas = ler_jsonl(saida)
    assert linhas[0]["decisao"] == "publicar" and linhas[0]["tema_central_id"] == 5527
