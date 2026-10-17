import json

import pytest
from pydantic import ValidationError

from classificador import custos, llm
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato
from classificador.config import ChaveAusenteError
from classificador.custos import LivroRazao, calcular_custo
from classificador.llm import ClassificadorLLM, VotoModelo

CANDIDATOS = [Candidato(5524, "tema", 0.7), Candidato(5527, "tema", 0.6), Candidato(5159, "tema", 0.3)]
TEMPLATE = "Q:\n{{QUESTAO}}\nC:\n{{CANDIDATOS}}"
USO = {"tokens_entrada": 1000, "tokens_saida": 400, "tokens_raciocinio": 150,
       "tokens_cache_leitura": 0, "tokens_cache_escrita": 0}


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def voto(tema, extras=(), confianca=0.9, disciplina="Processo Penal"):
    return VotoModelo(tema_central_id=tema, extras_ids=list(extras), disciplina=disciplina, confianca=confianca, justificativa="x")


class InvocadorFalso:
    """Devolve (voto, uso) como o invocador real; um voto solto vem com uso desconhecido."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta if isinstance(resposta, tuple) else (resposta, None)


def classificador(invocador, tmp_path, nome="falso", modelo="modelo-x", **kw):
    esperas = []
    clf = ClassificadorLLM(nome, modelo, invocador, tmp_path, TEMPLATE, dormir=esperas.append, **kw)
    return clf, esperas


def livro_em(tmp_path):
    return LivroRazao(tmp_path / "custos" / "chamadas.jsonl")


def linhas_do_livro(livro):
    return [json.loads(linha) for linha in livro.caminho.read_text(encoding="utf-8").splitlines()]


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
    assert json.loads(arquivo.read_text(encoding="utf-8"))["voto"]["tema_central_id"] == 5524


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


# --- livro-razão de custos -------------------------------------------------------------------------------


def test_cache_no_formato_antigo_e_lido_e_registrado_como_cache_sem_uso(arvore, tmp_path):
    livro = livro_em(tmp_path)
    clf, _ = classificador(None, tmp_path, livro=livro)
    prompt = llm.montar_prompt(TEMPLATE, "t", CANDIDATOS, arvore)
    arquivo = clf._arquivo(prompt)
    arquivo.write_text(voto(5527, confianca=0.8).model_dump_json(), encoding="utf-8")
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5527
    assert clf.acertos_cache == 1
    [linha] = linhas_do_livro(livro)
    assert (linha["origem"], linha["tentativa"], linha["sucesso"], linha["erro"]) == ("cache", 1, True, None)
    assert all(linha[campo] is None for campo in custos.CAMPOS_USO)
    assert linha["custo_usd"] == 0.0
    assert linha["latencia_ms"] is None
    assert (linha["provedor"], linha["modelo"], linha["tema_votado"], linha["confianca"]) == ("falso", "modelo-x", 5527, 0.8)
    assert linha["hash_prompt"] == arquivo.stem
    assert (linha["n_candidatos"], linha["tamanho_prompt_chars"]) == (3, len(prompt))
    # Ler não regrava: o arquivo antigo continua como estava.
    assert json.loads(arquivo.read_text(encoding="utf-8"))["tema_central_id"] == 5527


def test_chamada_real_grava_cache_no_formato_novo_e_linha_api_com_custo(arvore, tmp_path):
    livro = livro_em(tmp_path)
    inv = InvocadorFalso([(voto(5527), USO)])
    clf, _ = classificador(inv, tmp_path, modelo="gpt-5", livro=livro,
                           configuracao={"reasoning_effort": "low", "method": "json_schema"})
    clf.classificar("t", CANDIDATOS, arvore)
    arquivo = next((tmp_path / "llm").rglob("*.json"))
    gravado = json.loads(arquivo.read_text(encoding="utf-8"))
    assert set(gravado) == {"voto", "uso", "modelo", "quando"}
    assert gravado["voto"] == voto(5527).model_dump()
    assert gravado["uso"] == USO
    assert gravado["modelo"] == "gpt-5"
    [linha] = linhas_do_livro(livro)
    assert (linha["origem"], linha["tentativa"], linha["sucesso"], linha["erro"]) == ("api", 1, True, None)
    assert linha["configuracao"] == "json_schema_effort-low"
    assert linha["hash_prompt"] == arquivo.stem
    assert {campo: linha[campo] for campo in custos.CAMPOS_USO} == USO
    assert linha["custo_usd"] == pytest.approx(calcular_custo("gpt-5", USO))
    assert linha["custo_usd"] > 0
    assert linha["latencia_ms"] >= 0
    assert (linha["tema_votado"], linha["confianca"]) == (5527, 0.9)


def test_segunda_chamada_le_o_cache_novo_e_registra_o_uso_do_arquivo(arvore, tmp_path):
    livro = livro_em(tmp_path)
    inv = InvocadorFalso([(voto(5527), USO)])
    clf, _ = classificador(inv, tmp_path, modelo="gpt-5", livro=livro)
    primeiro = clf.classificar("t", CANDIDATOS, arvore)
    segundo = clf.classificar("t", CANDIDATOS, arvore)
    assert primeiro == segundo
    assert len(inv.prompts) == 1
    real, cache = linhas_do_livro(livro)
    assert (real["origem"], cache["origem"]) == ("api", "cache")
    assert {campo: cache[campo] for campo in custos.CAMPOS_USO} == USO
    assert cache["custo_usd"] == 0.0
    assert cache["latencia_ms"] is None
    assert cache["hash_prompt"] == real["hash_prompt"]


def test_falha_definitiva_registra_cada_tentativa_sem_sucesso(arvore, tmp_path):
    livro = livro_em(tmp_path)
    inv = InvocadorFalso([RuntimeError("503 indisponível")] * 3)
    clf, _ = classificador(inv, tmp_path, modelo="gpt-5", livro=livro)
    assert clf.classificar("t", CANDIDATOS, arvore) is None
    linhas = linhas_do_livro(livro)
    assert [l["tentativa"] for l in linhas] == [1, 2, 3]
    assert all(l["origem"] == "api" and l["sucesso"] is False for l in linhas)
    assert {l["erro"] for l in linhas} == {"RuntimeError: 503 indisponível"}
    assert all(l["custo_usd"] is None and l["tokens_entrada"] is None for l in linhas)
    assert all(l["tema_votado"] is None and l["latencia_ms"] is not None for l in linhas)


def test_mensagem_de_erro_fica_com_os_primeiros_200_caracteres(arvore, tmp_path):
    livro = livro_em(tmp_path)
    clf, _ = classificador(InvocadorFalso([RuntimeError("x" * 500)] * 3), tmp_path, livro=livro)
    clf.classificar("t", CANDIDATOS, arvore)
    assert {l["erro"] for l in linhas_do_livro(livro)} == {"RuntimeError: " + "x" * 200}


def test_erro_permanente_registra_a_tentativa_antes_de_subir(arvore, tmp_path):
    livro = livro_em(tmp_path)
    clf, _ = classificador(InvocadorFalso([ErroDeApi(401)]), tmp_path, livro=livro)
    with pytest.raises(ErroDeApi):
        clf.classificar("t", CANDIDATOS, arvore)
    [linha] = linhas_do_livro(livro)
    assert (linha["sucesso"], linha["erro"]) == (False, "ErroDeApi: status 401")


def test_retentativa_por_validacao_gera_uma_linha_por_tentativa(arvore, tmp_path):
    livro = livro_em(tmp_path)
    erro = erro_de_validacao()
    erro.uso_tokens = USO  # o invocador real anexa ao erro o uso da resposta fora do schema
    inv = InvocadorFalso([erro, (voto(5527), USO)])
    clf, _ = classificador(inv, tmp_path, modelo="gpt-5", livro=livro)
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5527
    primeira, segunda = linhas_do_livro(livro)
    assert (primeira["tentativa"], primeira["sucesso"]) == (1, False)
    assert primeira["erro"].startswith("ValidationError: ")
    assert primeira["tokens_entrada"] == USO["tokens_entrada"]
    assert primeira["custo_usd"] == pytest.approx(calcular_custo("gpt-5", USO))
    assert (segunda["tentativa"], segunda["sucesso"], segunda["tema_votado"]) == (2, True, 5527)
    # A segunda tentativa leva o aviso no prompt; o hash continua o da chave do cache.
    assert segunda["tamanho_prompt_chars"] > primeira["tamanho_prompt_chars"]
    assert segunda["hash_prompt"] == primeira["hash_prompt"]


def test_tema_fora_dos_candidatos_registra_a_tentativa_rejeitada(arvore, tmp_path):
    livro = livro_em(tmp_path)
    inv = InvocadorFalso([(voto(9999), USO), (voto(5527), USO)])
    clf, _ = classificador(inv, tmp_path, modelo="gpt-5", livro=livro)
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5527
    rejeitada, aceita = linhas_do_livro(livro)
    assert (rejeitada["sucesso"], rejeitada["erro"], rejeitada["tema_votado"]) == (False, "VotoInvalidoError: 9999", 9999)
    assert rejeitada["custo_usd"] > 0
    assert (aceita["tentativa"], aceita["sucesso"], aceita["tema_votado"]) == (2, True, 5527)


def test_sem_livro_injetado_usa_o_livro_global(arvore, tmp_path, livro_temporario):
    clf, _ = classificador(InvocadorFalso([voto(5524)]), tmp_path)
    clf.classificar("t", CANDIDATOS, arvore)
    assert [l["origem"] for l in linhas_do_livro(livro_temporario)] == ["api"]


def test_rodar_votos_registra_etapa_alvo_e_questao(arvore, tmp_path):
    candidatos = tmp_path / "cand.jsonl"
    gravar_candidatos(candidatos, ["Q0001", "Q0002"])
    livro = livro_em(tmp_path)
    a, _ = classificador(InvocadorFalso([voto(5524)] * 2), tmp_path / "a", nome="openai", livro=livro)
    b, _ = classificador(InvocadorFalso([voto(5524)] * 2), tmp_path / "b", nome="anthropic", livro=livro)
    llm.rodar_votos("questoes", arvore, candidatos, (a, b), pasta_saida=tmp_path, limite=2)
    assert [(l["etapa"], l["alvo"], l["id_questao"], l["provedor"]) for l in linhas_do_livro(livro)] == [
        ("votos", "questoes", "Q0001", "openai"),
        ("votos", "questoes", "Q0001", "anthropic"),
        ("votos", "questoes", "Q0002", "openai"),
        ("votos", "questoes", "Q0002", "anthropic"),
    ]
    assert custos.contexto_atual() == custos.Contexto()


# --- invocador real, com o modelo de chat trocado por um dublê --------------------------------------------


def modelo_de_chat_falso(resposta):
    """Classe no lugar de ChatOpenAI/ChatAnthropic: anota os parâmetros e devolve `resposta` no invoke."""
    anotado = {}

    class ChatFalso:
        def __init__(self, **parametros):
            anotado["parametros"] = parametros

        def with_structured_output(self, schema, **kwargs):
            anotado["estruturado"] = {"schema": schema, **kwargs}
            return self

        def invoke(self, prompt):
            anotado["prompt"] = prompt
            return resposta

    return ChatFalso, anotado


def test_invocador_pede_a_resposta_crua_e_devolve_voto_e_uso(monkeypatch):
    import langchain_openai
    from langchain_core.messages import AIMessage

    bruta = AIMessage(content="{}", usage_metadata={
        "input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500,
        "input_token_details": {"cache_read": 1000}, "output_token_details": {"reasoning": 120},
    })
    chat, anotado = modelo_de_chat_falso({"raw": bruta, "parsed": voto(5524), "parsing_error": None})
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", chat)
    resultado, uso = llm.criar_invocador("openai", "gpt-5")("prompt")
    assert resultado == voto(5524)
    assert uso == {"tokens_entrada": 1200, "tokens_saida": 300, "tokens_raciocinio": 120,
                   "tokens_cache_leitura": 1000, "tokens_cache_escrita": 0}
    assert anotado["estruturado"] == {"schema": VotoModelo, "method": "json_schema", "include_raw": True}
    assert anotado["parametros"] == {"model": "gpt-5", "reasoning_effort": "low"}


def test_invocador_sobe_o_erro_de_parse_como_hoje_com_o_uso_anexado(monkeypatch):
    import langchain_anthropic
    from langchain_core.exceptions import OutputParserException
    from langchain_core.messages import AIMessage

    embrulhado = OutputParserException("falha ao interpretar a saída")
    embrulhado.__cause__ = erro_de_validacao()
    bruta = AIMessage(content="{}", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    chat, _ = modelo_de_chat_falso({"raw": bruta, "parsed": None, "parsing_error": embrulhado})
    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", chat)
    with pytest.raises(OutputParserException) as capturado:
        llm.criar_invocador("anthropic", "claude-sonnet-5-5")("prompt")
    assert capturado.value is embrulhado
    assert llm.erro_de_validacao(capturado.value) is embrulhado.__cause__
    assert capturado.value.uso_tokens == {"tokens_entrada": 10, "tokens_saida": 5, "tokens_raciocinio": 0,
                                          "tokens_cache_leitura": 0, "tokens_cache_escrita": 0}


def test_invocador_sem_voto_e_sem_erro_de_parse_sobe_runtime_error(monkeypatch):
    import langchain_openai
    from langchain_core.messages import AIMessage

    chat, _ = modelo_de_chat_falso({"raw": AIMessage(content=""), "parsed": None, "parsing_error": None})
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", chat)
    with pytest.raises(RuntimeError, match="não é VotoModelo"):
        llm.criar_invocador("openai", "gpt-5")("prompt")


def test_verificar_registra_as_chamadas_na_etapa_verificar(monkeypatch, livro_temporario):
    monkeypatch.setenv("OPENAI_API_KEY", "chave-falsa")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-falsa")
    monkeypatch.setenv("MODELO_OPENAI", "gpt-5")
    monkeypatch.setenv("MODELO_ANTHROPIC", "claude-sonnet-5-5")

    def criar(provedor, modelo):
        if provedor == "anthropic":
            def falhar(prompt):
                raise ErroDeApi(401)
            return falhar
        return lambda prompt: (voto(1), USO)

    monkeypatch.setattr(llm, "criar_invocador", criar)
    assert llm.verificar_provedores() == {"openai": "ok", "anthropic": "erro: status 401"}
    certa, errada = linhas_do_livro(livro_temporario)
    assert (certa["etapa"], certa["provedor"], certa["modelo"], certa["origem"], certa["sucesso"]) == (
        "verificar", "openai", "gpt-5", "api", True)
    assert certa["configuracao"] == "json_schema_effort-low"
    assert certa["custo_usd"] == pytest.approx(calcular_custo("gpt-5", USO))
    assert (errada["etapa"], errada["provedor"], errada["sucesso"], errada["erro"]) == (
        "verificar", "anthropic", False, "ErroDeApi: status 401")
