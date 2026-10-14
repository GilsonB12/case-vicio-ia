import json

import pytest
from pydantic import ValidationError

from classificador import llm
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato
from classificador.config import ChaveAusenteError
from classificador.llm import ClassificadorLLM, VotoModelo

CANDIDATOS = [Candidato(5524, "tema", 0.7), Candidato(5527, "tema", 0.6), Candidato(5159, "tema", 0.3)]
TEMPLATE = "Q:\n{{QUESTAO}}\nC:\n{{CANDIDATOS}}"


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def voto(tema, extras=(), confianca=0.9, disciplina="Processo Penal"):
    return VotoModelo(tema_central_id=tema, extras_ids=list(extras), disciplina=disciplina, confianca=confianca, justificativa="x")


class InvocadorFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def classificador(invocador, tmp_path, nome="falso", **kw):
    esperas = []
    clf = ClassificadorLLM(nome, "modelo-x", invocador, tmp_path, TEMPLATE, dormir=esperas.append, **kw)
    return clf, esperas


class ErroDeApi(Exception):
    """Imita os erros dos SDKs da OpenAI e da Anthropic, que expõem status_code."""

    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def erro_de_validacao():
    try:
        VotoModelo.model_validate({"tema_central_id": 5524, "extras_ids": [], "disciplina": "Penal",
                                   "confianca": 1.5, "justificativa": "x"})
    except ValidationError as erro:
        return erro
    raise AssertionError("o voto com confianca 1.5 deveria falhar na validação")


def gravar_candidatos(caminho, ids):
    from classificador.dados import escrever_jsonl

    escrever_jsonl(caminho, [{"id": i, "candidatos": [{"tema_id": 5524, "origem": "tema", "similaridade": 0.5}]} for i in ids])


def test_montar_prompt_substitui_marcadores(arvore):
    prompt = llm.montar_prompt(TEMPLATE, "enunciado", CANDIDATOS[:1], arvore)
    assert "Q:\nenunciado" in prompt
    assert "- id 5524: Processo Penal > Procedimento do Tribunal do Júri" in prompt
    assert "{{" not in prompt


def test_segunda_chamada_vem_do_cache(arvore, tmp_path):
    inv = InvocadorFalso([voto(5527)])
    clf, _ = classificador(inv, tmp_path)
    primeiro = clf.classificar("t", CANDIDATOS, arvore)
    segundo = clf.classificar("t", CANDIDATOS, arvore)
    assert primeiro == segundo
    assert len(inv.prompts) == 1


def test_tema_fora_dos_candidatos_tenta_uma_vez_e_devolve_none(arvore, tmp_path):
    inv = InvocadorFalso([voto(9999), voto(9999)])
    clf, _ = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore) is None
    assert len(inv.prompts) == 2
    assert "9999" in inv.prompts[1]
    assert not list((tmp_path / "llm").rglob("*.json"))


def test_tema_invalido_depois_valido(arvore, tmp_path):
    inv = InvocadorFalso([voto(9999), voto(5527)])
    clf, _ = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5527


def test_extras_sao_filtrados_e_central_canonicalizado(arvore, tmp_path):
    inv = InvocadorFalso([voto(5527, extras=[5527, 5524, 4242])])
    clf, _ = classificador(inv, tmp_path)
    resultado = clf.classificar("t", CANDIDATOS, arvore)
    assert resultado.extras_ids == [5524]


def test_erro_de_api_retenta_com_espera_exponencial(arvore, tmp_path):
    inv = InvocadorFalso([RuntimeError("503"), RuntimeError("503"), voto(5524)])
    clf, esperas = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5524
    assert esperas == [2.0, 4.0]


def test_erro_de_api_persistente_devolve_none(arvore, tmp_path):
    inv = InvocadorFalso([RuntimeError("x")] * 3)
    clf, _ = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore) is None
    assert len(inv.prompts) == 3


def test_sem_invocador_e_sem_cache_levanta_chave_ausente(arvore, tmp_path):
    clf, _ = classificador(None, tmp_path)
    with pytest.raises(ChaveAusenteError, match="falso"):
        clf.classificar("t", CANDIDATOS, arvore)


def test_cache_corrompido_e_regravado(arvore, tmp_path):
    inv = InvocadorFalso([voto(5527), voto(5524)])
    clf, _ = classificador(inv, tmp_path)
    clf.classificar("t", CANDIDATOS, arvore)
    arquivo = next((tmp_path / "llm").rglob("*.json"))
    arquivo.write_text("{quebrado", encoding="utf-8")
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5524
    assert json.loads(arquivo.read_text(encoding="utf-8"))["tema_central_id"] == 5524


def test_voto_none_e_disciplina_outra_sao_validos(arvore, tmp_path):
    inv = InvocadorFalso([voto(None, disciplina="Outra", confianca=0.2)])
    clf, _ = classificador(inv, tmp_path)
    resultado = clf.classificar("t", CANDIDATOS, arvore)
    assert resultado.tema_central_id is None
    assert resultado.disciplina == "Outra"


def test_rodar_votos_grava_jsonl(arvore, tmp_path):
    from classificador.dados import escrever_jsonl, ler_jsonl

    candidatos = tmp_path / "cand.jsonl"
    escrever_jsonl(candidatos, [
        {"id": "Q0001", "candidatos": [{"tema_id": 5524, "origem": "tema", "similaridade": 0.5}]},
        {"id": "Q0002", "candidatos": [{"tema_id": 5524, "origem": "tema", "similaridade": 0.5}]},
    ])
    a, _ = classificador(InvocadorFalso([voto(5524), voto(5524)]), tmp_path / "a")
    b, _ = classificador(InvocadorFalso([voto(5524), RuntimeError("x"), RuntimeError("x"), RuntimeError("x")]), tmp_path / "b")
    saida = llm.rodar_votos("questoes", arvore, candidatos, (a, b), pasta_saida=tmp_path, limite=2)
    linhas = ler_jsonl(saida)
    assert [l["id"] for l in linhas] == ["Q0001", "Q0002"]
    assert linhas[0]["openai"]["tema_central_id"] == 5524
    assert linhas[1]["anthropic"] is None


def test_erro_4xx_nao_e_retentado(arvore, tmp_path):
    inv = InvocadorFalso([ErroDeApi(401), voto(5524)])
    clf, esperas = classificador(inv, tmp_path)
    with pytest.raises(ErroDeApi):
        clf.classificar("t", CANDIDATOS, arvore)
    assert len(inv.prompts) == 1
    assert esperas == []


def test_erro_429_e_retentado(arvore, tmp_path):
    inv = InvocadorFalso([ErroDeApi(429), ErroDeApi(429), voto(5524)])
    clf, esperas = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5524
    assert esperas == [2.0, 4.0]


def test_validation_error_tenta_uma_vez_e_devolve_none(arvore, tmp_path):
    erro = erro_de_validacao()
    inv = InvocadorFalso([erro, erro])
    clf, esperas = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore) is None
    assert len(inv.prompts) == 2
    assert esperas == []
    assert "schema" in inv.prompts[1] and "confianca" in inv.prompts[1]


def test_validation_error_encadeado_tambem_tenta_uma_vez(arvore, tmp_path):
    # O parser do LangChain para a Anthropic embrulha o ValidationError em outra exceção.
    embrulhado = ValueError("falha ao interpretar a saída")
    embrulhado.__cause__ = erro_de_validacao()
    inv = InvocadorFalso([embrulhado, voto(5527)])
    clf, esperas = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5527
    assert len(inv.prompts) == 2
    assert esperas == []


def test_disjuntor_para_apos_cinco_none_consecutivos(arvore, tmp_path):
    from classificador.dados import carregar_questoes

    ids = [str(i) for i in carregar_questoes()["id"][:6]]
    candidatos = tmp_path / "cand.jsonl"
    gravar_candidatos(candidatos, ids)
    a, _ = classificador(InvocadorFalso([voto(5524)] * 6), tmp_path / "a", nome="bom")
    b, _ = classificador(InvocadorFalso([RuntimeError("x")] * 18), tmp_path / "b", nome="quebrado")
    with pytest.raises(RuntimeError, match="quebrado") as erro:
        llm.rodar_votos("questoes", arvore, candidatos, (a, b), pasta_saida=tmp_path, limite=6)
    assert "votos --verificar" in str(erro.value)
    assert len(a.invocador.prompts) == llm.MAXIMO_NONE_CONSECUTIVOS


def test_rodar_votos_acusa_questao_sem_candidatos(arvore, tmp_path):
    candidatos = tmp_path / "cand.jsonl"
    gravar_candidatos(candidatos, ["Q0001"])
    a, _ = classificador(InvocadorFalso([voto(5524)] * 2), tmp_path / "a")
    b, _ = classificador(InvocadorFalso([voto(5524)] * 2), tmp_path / "b")
    with pytest.raises(KeyError, match="Q0002.*cand.jsonl"):
        llm.rodar_votos("questoes", arvore, candidatos, (a, b), pasta_saida=tmp_path, limite=2)


def test_configuracao_diferente_nao_compartilha_cache(arvore, tmp_path):
    inv_baixo = InvocadorFalso([voto(5527)])
    baixo, _ = classificador(inv_baixo, tmp_path, configuracao={"effort": "low", "method": "json_schema"})
    baixo.classificar("t", CANDIDATOS, arvore)
    inv_alto = InvocadorFalso([voto(5524)])
    alto, _ = classificador(inv_alto, tmp_path, configuracao={"effort": "high", "method": "json_schema"})
    assert alto.classificar("t", CANDIDATOS, arvore).tema_central_id == 5524
    assert len(inv_alto.prompts) == 1
    assert baixo.pasta != alto.pasta
    assert baixo.pasta.name == "modelo-x__effort-low_json_schema"
