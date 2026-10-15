import pandas as pd
import pytest

from analise import heuristicas
from classificador.dados import carregar_questoes, carregar_temas


@pytest.fixture(scope="module")
def questoes():
    return carregar_questoes()


@pytest.fixture(scope="module")
def temas():
    return carregar_temas()


@pytest.fixture(scope="module")
def ocr(questoes):
    return heuristicas.marcar_corrupcao_ocr(questoes)


# Vocabulário e proporção fora dele


def test_vocabulario_ignora_token_de_um_texto_so():
    vocabulario = heuristicas.montar_vocabulario([
        "Furto qualificado pelo concurso",
        "furto simples e concurso material",
        "estelionato",
    ])
    assert "furto" in vocabulario
    assert "concurso" in vocabulario
    assert "estelionato" not in vocabulario
    assert "qualificado" not in vocabulario


def test_vocabulario_conta_textos_distintos_e_nao_repeticoes():
    vocabulario = heuristicas.montar_vocabulario(["roubo roubo roubo", "furto"])
    assert "roubo" not in vocabulario


def test_vocabulario_minusculo_sem_acento_e_com_tres_letras_ou_mais():
    vocabulario = heuristicas.montar_vocabulario([
        "Ação PENAL de ofício",
        "acao penal de oficio",
    ])
    assert vocabulario == {"acao", "penal", "oficio"}


def test_proporcao_zero_para_texto_vazio():
    assert heuristicas.proporcao_fora_do_vocabulario("", {"furto"}) == 0.0
    assert heuristicas.proporcao_fora_do_vocabulario("a, 1 e 2.", {"furto"}) == 0.0


def test_proporcao_conta_tokens_fora_do_vocabulario():
    vocabulario = {"furto", "qualificado"}
    assert heuristicas.proporcao_fora_do_vocabulario("Furto qualificado xptoqz", vocabulario) == pytest.approx(1 / 3)


def test_texto_juridico_com_latim_e_sigla_conhecidos_tem_proporcao_zero():
    vocabulario = heuristicas.montar_vocabulario([
        "O STF concedeu habeas corpus por abolitio criminis.",
        "Habeas corpus no STF e abolitio criminis na lei nova.",
    ])
    texto = "STF: habeas corpus e abolitio criminis."
    assert heuristicas.proporcao_fora_do_vocabulario(texto, vocabulario) == 0.0


# Corrupção de OCR nas 359 questões


def test_ocr_tem_uma_linha_por_questao_ordenada_por_proporcao(ocr, questoes):
    assert list(ocr.columns) == ["id", "proporcao", "suspeita"]
    assert len(ocr) == len(questoes) == 359
    assert ocr["proporcao"].is_monotonic_decreasing
    assert ocr["suspeita"].dtype == bool


def test_ocr_marca_q0078_e_nao_marca_q0001(ocr):
    por_id = ocr.set_index("id")
    assert bool(por_id.loc["Q0078", "suspeita"])
    assert not bool(por_id.loc["Q0001", "suspeita"])


def test_ocr_nao_marca_questoes_juridicas_com_habeas_corpus(ocr, questoes):
    com_latim = questoes.loc[questoes["texto"].str.contains("habeas corpus", case=False), "id"]
    assert len(com_latim) >= 5
    marcadas = set(ocr.loc[ocr["suspeita"], "id"])
    assert marcadas.isdisjoint(com_latim)


def test_ocr_exclui_a_propria_questao_do_vocabulario():
    questoes = pd.DataFrame({
        "id": ["Q1", "Q2", "Q3"],
        "texto": ["furto roubo xptoqz xptoqz", "furto roubo", "furto roubo"],
    })
    temas = pd.DataFrame({"caminho": ["Penal > Furto"], "descricao": ["Subtema de furto."]})
    resultado = heuristicas.marcar_corrupcao_ocr(questoes, limiar=0.25, temas=temas).set_index("id")
    assert resultado.loc["Q1", "proporcao"] == pytest.approx(0.5)
    assert bool(resultado.loc["Q1", "suspeita"])
    assert resultado.loc["Q2", "proporcao"] == 0.0


# Enunciado genérico


@pytest.mark.parametrize("enunciado", [
    "Assinale a alternativa correta.",
    "Assinale a alternativa CORRETA.",
    "Assinale a alternativa correta:",
    "Assinale a alternativa correta :",
    "Assinale a alternativa INCORRETA:",
    "Assinale a afirmativa incorreta.",
    "Marque a opção INCORRETA.",
    "Marque a alternativa correta do ponto de vista legal.",
    "Analise a opção CORRETA.",
    "Assinale a opcao correta.",
    "Julgue o item a seguir.",
    "assinale a alternativa correta",
])
def test_enunciado_generico_reconhece_variantes(enunciado):
    assert heuristicas.eh_enunciado_generico(enunciado)


@pytest.mark.parametrize("enunciado", [
    "Francisco foi processado pelo Ministério Público pelo delito de furto.",
    "A respeito da culpabilidade, assinale a opção correta.",
    "Assinale a alternativa que corresponde a uma operação isenta do Imposto sobre a Transmissão",
    "O habeas corpus é",
    "",
])
def test_enunciado_com_conteudo_nao_e_generico(enunciado):
    assert not heuristicas.eh_enunciado_generico(enunciado)


# Enunciados repetidos


def test_grupos_de_enunciado_repetido(questoes):
    grupos = heuristicas.grupos_de_enunciado_repetido(questoes)
    assert all(len(grupo) >= 2 for grupo in grupos)
    assert any({"Q0090", "Q0205"} <= set(grupo) for grupo in grupos)
    assert any({"Q0268", "Q0321"} <= set(grupo) and "Q0090" not in grupo for grupo in grupos)


def test_grupos_normalizam_caixa_acento_e_espacos():
    questoes = pd.DataFrame({
        "id": ["Q1", "Q2", "Q3"],
        "enunciado_html": [
            "Assinale a <b>opção</b>  CORRETA.",
            "assinale a opcao correta.",
            "Outro enunciado.",
        ],
    })
    assert heuristicas.grupos_de_enunciado_repetido(questoes) == [["Q1", "Q2"]]


# Defeitos da árvore


def test_defeitos_da_arvore(temas):
    defeitos = heuristicas.defeitos_da_arvore(temas)
    assert list(defeitos.columns) == ["tema_id", "titulo", "defeito"]
    por_defeito = defeitos.groupby("defeito")["tema_id"].apply(set)

    duplicados = por_defeito["duplicado_sem_descricao"]
    assert len(duplicados) == 20
    assert all(6716 <= tema_id <= 6738 for tema_id in duplicados)
    assert por_defeito["inativo"] == {5078, 5234}
    assert 4696 in por_defeito["titulo_com_erro"]
    assert len(por_defeito["descricao_com_caracteres_estranhos"]) >= 1


def test_zero_questoes_nao_confunde_com_50_questoes(temas):
    defeitos = heuristicas.defeitos_da_arvore(temas)
    zero = set(defeitos.loc[defeitos["defeito"] == "zero_questoes", "tema_id"])
    assert 5190 in zero
    assert 5078 not in zero  # "50 questões no source"


def test_caracteres_estranhos_tolera_acentos_aspas_e_simbolos():
    temas = pd.DataFrame({
        "tema_id": [1, 2],
        "parent_id": pd.array([None, 1], dtype="Int64"),
        "titulo": ["Raiz", "Filho"],
        "descricao": [
            "Ação – “citação” § 1º, 30° e coerção.",
            "Procedimento علف ordinário.",
        ],
        "ativo": [True, True],
    })
    defeitos = heuristicas.defeitos_da_arvore(temas)
    estranhos = set(defeitos.loc[defeitos["defeito"] == "descricao_com_caracteres_estranhos", "tema_id"])
    assert estranhos == {2}


# Questões fora do escopo


def test_questoes_fora_do_escopo(questoes):
    fora = heuristicas.questoes_fora_do_escopo(questoes)
    assert list(fora.columns) == ["id", "disciplina_origem", "assunto_origem", "inicio"]
    assert len(fora) == 8
    assert "Q0142" in set(fora["id"])
    assert "" in set(fora["disciplina_origem"])
    assert fora["inicio"].str.len().max() <= 120
