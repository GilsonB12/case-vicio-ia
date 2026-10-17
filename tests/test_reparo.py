import logging

import pandas as pd
import pytest

from classificador import pipeline, reparo
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato, candidatos_para_dict
from classificador.dados import escrever_jsonl, ler_jsonl
from classificador.indice import Resultado
from classificador.llm import VotoModelo
from classificador.reparo import expandir_candidatos, rodar_reparo
from tests.fakes import EmbeddingsFalsas

# 5524 Tribunal do Júri (nível 1), 5527 subtema dele (nível 2), 5159 Furto (nível 2, pai 5157).
ORIGINAIS = [Candidato(5524, "tema", 0.7), Candidato(5527, "tema", 0.65), Candidato(5159, "tema", 0.4)]


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def voto(tema, disciplina="Legislação Especial", justificativa="x", confianca=0.9, extras=()):
    return VotoModelo(tema_central_id=tema, extras_ids=list(extras), disciplina=disciplina,
                      confianca=confianca, justificativa=justificativa)


def dump(v):
    return None if v is None else v.model_dump()


class IndiceFalso:
    """Devolve resultados fixos por texto de consulta e anota as buscas."""

    def __init__(self, respostas):
        self.nome = "Tema"
        self.respostas = respostas
        self.buscas = []
        self.fechado = False

    def adicionar(self, ids, textos, metadados):
        pass

    def buscar(self, texto, k, excluir=frozenset()):
        self.buscas.append((texto, k))
        return [Resultado(str(t), {"tema_id": t}, s) for t, s in self.respostas.get(texto, [])][:k]

    def tamanho(self):
        return 0

    def fechar(self):
        self.fechado = True


class ClassificadorFalso:
    """Responde por texto da questão e conta as chamadas, como o ClassificadorLLM."""

    def __init__(self, nome, respostas=None):
        self.nome = nome
        self.respostas = dict(respostas or {})
        self.chamadas = 0
        self.acertos_cache = 0
        self.recebidos = []

    def classificar(self, texto, candidatos, arvore):
        self.chamadas += 1
        self.recebidos.append((texto, list(candidatos)))
        return self.respostas.get(texto)


# --- expandir_candidatos ---------------------------------------------------------------------------------


def test_tema_novo_entra_com_origem_reparo_e_so_o_voto_nulo_busca(arvore):
    votos = {"openai": dump(voto(None, justificativa="porte ilegal de arma de fogo")), "anthropic": dump(voto(5524))}
    indice = IndiceFalso({"porte ilegal de arma de fogo": [(4697, 0.8)]})
    lista, novos = expandir_candidatos(ORIGINAIS, votos, indice, arvore, k=5, teto=18)
    assert lista == ORIGINAIS + [Candidato(4697, "reparo", 0.8)]
    assert novos == [4697]
    assert indice.buscas == [("porte ilegal de arma de fogo", 5)]


def test_voto_sem_resposta_nao_busca(arvore):
    votos = {"openai": None, "anthropic": dump(voto(None, justificativa="confissão do acusado"))}
    indice = IndiceFalso({"confissão do acusado": [(4697, 0.5)]})
    expandir_candidatos(ORIGINAIS, votos, indice, arvore, k=5, teto=18)
    assert indice.buscas == [("confissão do acusado", 5)]


def test_pai_de_nivel_2_novo_entra_como_pai_antes_do_filho(arvore):
    votos = {"openai": dump(voto(None, justificativa="confissão")), "anthropic": dump(voto(5524))}
    indice = IndiceFalso({"confissão": [(5548, 0.75)]})
    lista, novos = expandir_candidatos(ORIGINAIS, votos, indice, arvore, k=5, teto=18)
    assert lista[len(ORIGINAIS):] == [Candidato(5543, "pai", 0.75), Candidato(5548, "reparo", 0.75)]
    assert novos == [5543, 5548]


def test_tema_ja_presente_nao_duplica_nem_puxa_pai(arvore):
    votos = {"openai": dump(voto(None, justificativa="j")), "anthropic": None}
    # 5524 e 5159 já estão na lista; o pai de 5159 (5157) não entra porque 5159 não é novo.
    indice = IndiceFalso({"j": [(5524, 0.95), (5159, 0.9), (4697, 0.5)]})
    lista, novos = expandir_candidatos(ORIGINAIS, votos, indice, arvore, k=5, teto=18)
    assert lista == ORIGINAIS + [Candidato(4697, "reparo", 0.5)]
    assert novos == [4697]


def test_pai_ja_presente_nao_duplica(arvore):
    originais = [Candidato(5524, "tema", 0.7), Candidato(5159, "tema", 0.4)]
    votos = {"openai": dump(voto(None, justificativa="j")), "anthropic": dump(voto(5524))}
    indice = IndiceFalso({"j": [(5527, 0.6)]})
    lista, novos = expandir_candidatos(originais, votos, indice, arvore, k=5, teto=18)
    assert lista == originais + [Candidato(5527, "reparo", 0.6)]
    assert novos == [5527]


def test_nao_publicavel_e_ignorado_e_duplicado_vira_canonico(arvore):
    votos = {"openai": dump(voto(None, justificativa="j")), "anthropic": dump(voto(5524))}
    # 4683 é raiz de disciplina, 5078 está inativo, 999999 não existe; 6735 é duplicata de 5543.
    indice = IndiceFalso({"j": [(4683, 0.9), (5078, 0.85), (999999, 0.8), (6735, 0.7)]})
    lista, novos = expandir_candidatos(ORIGINAIS, votos, indice, arvore, k=5, teto=18)
    assert lista == ORIGINAIS + [Candidato(5543, "reparo", 0.7)]
    assert novos == [5543]


def test_ordem_dos_originais_preservada_e_novos_por_similaridade(arvore):
    originais = [Candidato(5159, "tema", 0.3), Candidato(5524, "tema", 0.7)]
    votos = {"openai": dump(voto(None, justificativa="a")), "anthropic": dump(voto(None, justificativa="b"))}
    indice = IndiceFalso({"a": [(4697, 0.6)], "b": [(4697, 0.9), (5548, 0.8)]})
    lista, novos = expandir_candidatos(originais, votos, indice, arvore, k=5, teto=18)
    assert lista == originais + [
        Candidato(4697, "reparo", 0.9),
        Candidato(5543, "pai", 0.8),
        Candidato(5548, "reparo", 0.8),
    ]
    assert novos == [4697, 5543, 5548]
    assert indice.buscas == [("a", 5), ("b", 5)]


def test_teto_respeitado(arvore):
    votos = {"openai": dump(voto(None, justificativa="j")), "anthropic": dump(voto(5524))}
    indice = IndiceFalso({"j": [(4697, 0.8), (5548, 0.7)]})
    lista, novos = expandir_candidatos(ORIGINAIS, votos, indice, arvore, k=5, teto=5)
    assert len(lista) == 5
    assert lista[:3] == ORIGINAIS
    assert novos == [4697, 5543]


def test_sem_tema_novo_devolve_lista_original(arvore):
    votos = {"openai": dump(voto(None, justificativa="j")), "anthropic": dump(voto(None, justificativa=""))}
    indice = IndiceFalso({"j": [(5524, 0.9)]})
    lista, novos = expandir_candidatos(ORIGINAIS, votos, indice, arvore, k=5, teto=18)
    assert lista == ORIGINAIS
    assert novos == []
    assert indice.buscas == [("j", 5)]


# --- rodar_reparo ----------------------------------------------------------------------------------------

TEXTOS = {
    "Q0001": "questão sobre porte de arma",
    "Q0002": "questão de direito civil",
    "Q0003": "questão de júri",
    "Q0004": "questão de furto",
    "Q0005": "questão sem tema novo",
}

VOTOS_ORIGINAIS = [
    {"id": "Q0001", "openai": dump(voto(None, justificativa="porte ilegal de arma de fogo")),
     "anthropic": dump(voto(5524, confianca=0.4))},
    {"id": "Q0002", "openai": dump(voto(None, disciplina="Outra", justificativa="direito civil")),
     "anthropic": dump(voto(None, disciplina="Outra", justificativa="contratos"))},
    {"id": "Q0003", "openai": dump(voto(5524)), "anthropic": dump(voto(5527))},
    {"id": "Q0004", "openai": None, "anthropic": dump(voto(5159, disciplina="Penal"))},
    {"id": "Q0005", "openai": dump(voto(None, disciplina="Penal", justificativa="nada novo")),
     "anthropic": dump(voto(None, disciplina="Penal", justificativa="nada novo"))},
]

RESPOSTAS_INDICE = {
    "porte ilegal de arma de fogo": [(4697, 0.8)],
    "direito civil": [(4697, 0.9)],
    "contratos": [(5548, 0.9)],
    "nada novo": [(5524, 0.9)],
}


@pytest.fixture
def cenario(monkeypatch, tmp_path):
    escrever_jsonl(tmp_path / "votos_llm_questoes.jsonl", VOTOS_ORIGINAIS)
    escrever_jsonl(tmp_path / "candidatos_questoes_p2.jsonl",
                   [{"id": i, "candidatos": candidatos_para_dict(ORIGINAIS)} for i in TEXTOS])
    monkeypatch.setattr(reparo, "carregar_questoes",
                        lambda: pd.DataFrame({"id": list(TEXTOS), "texto": list(TEXTOS.values())}))
    return tmp_path


def classificadores_falsos():
    return (
        ClassificadorFalso("openai", {TEXTOS["Q0001"]: voto(4697, confianca=0.95)}),
        ClassificadorFalso("anthropic", {TEXTOS["Q0001"]: voto(4697, confianca=0.85)}),
    )


def rodar(pasta, classificadores, indice, recalcular=False):
    criados = []

    def criar(nome, embeddings):
        criados.append(nome)
        return indice

    saida = rodar_reparo("questoes", ArvoreTemas.carregar(), EmbeddingsFalsas(), classificadores,
                         pasta=pasta, criar=criar, recalcular=recalcular)
    return saida, criados


def test_rodar_reparo_revota_so_a_questao_com_voto_nulo_e_tema_novo(cenario):
    indice = IndiceFalso(RESPOSTAS_INDICE)
    classificadores = classificadores_falsos()
    saida, _ = rodar(cenario, classificadores, indice)
    assert saida == cenario / "votos_llm_questoes.jsonl"
    linhas = ler_jsonl(saida)
    assert [l["id"] for l in linhas] == list(TEXTOS)

    primeira = linhas[0]
    assert primeira["openai"] == dump(voto(4697, confianca=0.95))
    assert primeira["anthropic"] == dump(voto(4697, confianca=0.85))
    assert primeira["antes_do_reparo"] == {"openai": VOTOS_ORIGINAIS[0]["openai"],
                                           "anthropic": VOTOS_ORIGINAIS[0]["anthropic"]}
    assert primeira["reparo"] == {"novos": [4697], "revotado": True}

    esperada = ORIGINAIS + [Candidato(4697, "reparo", 0.8)]
    for clf in classificadores:
        assert clf.chamadas == 1
        assert clf.recebidos == [(TEXTOS["Q0001"], esperada)]

    # Os dois em outra disciplina (regra 1), sem voto nulo e voto ausente com o outro válido: intactas.
    assert linhas[1] == VOTOS_ORIGINAIS[1]
    assert linhas[2] == VOTOS_ORIGINAIS[2]
    assert linhas[3] == VOTOS_ORIGINAIS[3]
    assert ("direito civil", reparo.K_REPARO) not in indice.buscas

    # Elegível sem tema novo: marcada, sem revotação e com os votos originais.
    assert linhas[4] == {**VOTOS_ORIGINAIS[4], "reparo": {"novos": [], "revotado": False}}

    assert ler_jsonl(cenario / "candidatos_questoes_reparo.jsonl") == [
        {"id": "Q0001", "candidatos": candidatos_para_dict(esperada)},
    ]
    assert indice.fechado


def test_segunda_execucao_sem_recalcular_nao_chama_classificador(cenario):
    rodar(cenario, classificadores_falsos(), IndiceFalso(RESPOSTAS_INDICE))
    votos_antes = ler_jsonl(cenario / "votos_llm_questoes.jsonl")
    candidatos_antes = ler_jsonl(cenario / "candidatos_questoes_reparo.jsonl")

    classificadores = classificadores_falsos()
    indice = IndiceFalso(RESPOSTAS_INDICE)
    _, criados = rodar(cenario, classificadores, indice)
    assert [clf.chamadas for clf in classificadores] == [0, 0]
    assert criados == []
    assert indice.buscas == []
    assert ler_jsonl(cenario / "votos_llm_questoes.jsonl") == votos_antes
    # A lista ampliada da rodada anterior continua no arquivo.
    assert ler_jsonl(cenario / "candidatos_questoes_reparo.jsonl") == candidatos_antes


def test_recalcular_revota_a_partir_dos_votos_originais(cenario):
    rodar(cenario, classificadores_falsos(), IndiceFalso(RESPOSTAS_INDICE))
    classificadores = (
        ClassificadorFalso("openai", {TEXTOS["Q0001"]: voto(4697, confianca=0.7)}),
        ClassificadorFalso("anthropic", {TEXTOS["Q0001"]: voto(4697, confianca=0.6)}),
    )
    indice = IndiceFalso(RESPOSTAS_INDICE)
    rodar(cenario, classificadores, indice, recalcular=True)
    assert [clf.chamadas for clf in classificadores] == [1, 1]
    linhas = ler_jsonl(cenario / "votos_llm_questoes.jsonl")
    assert linhas[0]["openai"] == dump(voto(4697, confianca=0.7))
    assert linhas[0]["antes_do_reparo"] == {"openai": VOTOS_ORIGINAIS[0]["openai"],
                                           "anthropic": VOTOS_ORIGINAIS[0]["anthropic"]}
    assert linhas[0]["reparo"] == {"novos": [4697], "revotado": True}
    assert linhas[1:4] == VOTOS_ORIGINAIS[1:4]
    assert linhas[4] == {**VOTOS_ORIGINAIS[4], "reparo": {"novos": [], "revotado": False}}
    assert [l["id"] for l in ler_jsonl(cenario / "candidatos_questoes_reparo.jsonl")] == ["Q0001"]
    assert indice.fechado


def test_log_final_resume_o_reparo(cenario, caplog):
    with caplog.at_level(logging.INFO, logger="classificador.reparo"):
        rodar(cenario, classificadores_falsos(), IndiceFalso(RESPOSTAS_INDICE))
    mensagem = caplog.records[-1].getMessage()
    assert "2 elegíveis" in mensagem
    assert "1 revotadas" in mensagem
    assert "1 votos nulos deixaram de ser nulos" in mensagem
    assert "chamadas openai=1 anthropic=1" in mensagem


def test_classificador_sem_contadores_nao_quebra_o_log(cenario, caplog):
    class SemContador:
        def __init__(self, nome):
            self.nome = nome

        def classificar(self, texto, candidatos, arvore):
            return voto(4697)

    with caplog.at_level(logging.INFO, logger="classificador.reparo"):
        rodar(cenario, (SemContador("openai"), SemContador("anthropic")), IndiceFalso(RESPOSTAS_INDICE))
    mensagem = caplog.records[-1].getMessage()
    assert "1 revotadas" in mensagem
    assert "chamadas" not in mensagem


def test_indice_e_fechado_quando_a_revotacao_falha(cenario):
    class Quebrado(ClassificadorFalso):
        def classificar(self, texto, candidatos, arvore):
            raise RuntimeError("falhou")

    indice = IndiceFalso(RESPOSTAS_INDICE)
    with pytest.raises(RuntimeError, match="falhou"):
        rodar(cenario, (Quebrado("openai"), Quebrado("anthropic")), indice)
    assert indice.fechado
    # Nada é regravado quando a etapa quebra no meio.
    assert ler_jsonl(cenario / "votos_llm_questoes.jsonl") == VOTOS_ORIGINAIS


def test_reparo_do_corpus_le_o_corpus(monkeypatch, tmp_path):
    escrever_jsonl(tmp_path / "votos_llm_corpus.jsonl", [VOTOS_ORIGINAIS[0] | {"id": "C0001"}])
    escrever_jsonl(tmp_path / "candidatos_corpus_p2.jsonl", [{"id": "C0001", "candidatos": candidatos_para_dict(ORIGINAIS)}])
    monkeypatch.setattr(reparo, "carregar_questoes", lambda: pytest.fail("o alvo corpus não lê as questões"))
    monkeypatch.setattr(reparo, "carregar_corpus", lambda: pd.DataFrame({"id": ["C0001"], "texto": ["texto do corpus"]}))
    classificadores = (
        ClassificadorFalso("openai", {"texto do corpus": voto(4697)}),
        ClassificadorFalso("anthropic", {"texto do corpus": voto(4697)}),
    )
    saida = rodar_reparo("corpus", ArvoreTemas.carregar(), EmbeddingsFalsas(), classificadores, pasta=tmp_path,
                         criar=lambda nome, embeddings: IndiceFalso(RESPOSTAS_INDICE))
    assert saida == tmp_path / "votos_llm_corpus.jsonl"
    assert ler_jsonl(saida)[0]["reparo"] == {"novos": [4697], "revotado": True}
    assert [l["id"] for l in ler_jsonl(tmp_path / "candidatos_corpus_reparo.jsonl")] == ["C0001"]


def test_sem_votos_pede_para_rodar_os_votos(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"classificar votos --alvo questoes"):
        rodar_reparo("questoes", ArvoreTemas.carregar(), EmbeddingsFalsas(), classificadores_falsos(), pasta=tmp_path)


def test_alvo_invalido(tmp_path):
    with pytest.raises(ValueError, match="alvo"):
        rodar_reparo("outro", ArvoreTemas.carregar(), EmbeddingsFalsas(), classificadores_falsos(), pasta=tmp_path)


# --- rodar_reparo com a lista ampliada já gravada --------------------------------------------------------

# Lista ampliada de Q0001 numa execução anterior, diferente da que o índice falso montaria hoje (4697). 5159 tem
# origem "reparo" mas já está na p2 e 4697 não está na p2 mas tem origem "tema": nenhum dos dois conta como novo.
GRAVADA = [
    Candidato(5524, "tema", 0.7),
    Candidato(5527, "tema", 0.65),
    Candidato(5159, "reparo", 0.4),
    Candidato(4697, "tema", 0.3),
    Candidato(5543, "pai", 0.75),
    Candidato(5548, "reparo", 0.75),
]


def gravar_reparo_anterior(pasta, listas):
    escrever_jsonl(pasta / "candidatos_questoes_reparo.jsonl",
                   [{"id": id_, "candidatos": candidatos_para_dict(lista)} for id_, lista in listas.items()])


def so_q0001_pendente(pasta):
    """Q0005 já reparada; a única pendente é a Q0001."""
    escrever_jsonl(pasta / "votos_llm_questoes.jsonl",
                   VOTOS_ORIGINAIS[:4] + [{**VOTOS_ORIGINAIS[4], "reparo": {"novos": [], "revotado": False}}])


def test_pendente_com_lista_gravada_revota_sobre_ela_sem_buscar_no_indice(cenario):
    so_q0001_pendente(cenario)
    gravar_reparo_anterior(cenario, {"Q0001": GRAVADA})
    indice = IndiceFalso(RESPOSTAS_INDICE)
    classificadores = classificadores_falsos()
    rodar(cenario, classificadores, indice)

    assert indice.buscas == []
    for clf in classificadores:
        assert clf.recebidos == [(TEXTOS["Q0001"], GRAVADA)]
    primeira = ler_jsonl(cenario / "votos_llm_questoes.jsonl")[0]
    assert primeira["reparo"] == {"novos": [5543, 5548], "revotado": True}
    assert primeira["openai"] == dump(voto(4697, confianca=0.95))
    assert primeira["antes_do_reparo"] == {"openai": VOTOS_ORIGINAIS[0]["openai"],
                                           "anthropic": VOTOS_ORIGINAIS[0]["anthropic"]}
    assert ler_jsonl(cenario / "candidatos_questoes_reparo.jsonl") == [
        {"id": "Q0001", "candidatos": candidatos_para_dict(GRAVADA)},
    ]


def test_pendente_sem_lista_gravada_busca_no_indice(cenario):
    so_q0001_pendente(cenario)
    # O arquivo existe, mas só com a lista de outra questão.
    gravar_reparo_anterior(cenario, {"Q0003": GRAVADA})
    indice = IndiceFalso(RESPOSTAS_INDICE)
    classificadores = classificadores_falsos()
    _, criados = rodar(cenario, classificadores, indice)

    assert criados == ["Tema"]
    assert indice.buscas == [("porte ilegal de arma de fogo", reparo.K_REPARO)]
    esperada = ORIGINAIS + [Candidato(4697, "reparo", 0.8)]
    for clf in classificadores:
        assert clf.recebidos == [(TEXTOS["Q0001"], esperada)]
    assert ler_jsonl(cenario / "votos_llm_questoes.jsonl")[0]["reparo"] == {"novos": [4697], "revotado": True}
    assert ler_jsonl(cenario / "candidatos_questoes_reparo.jsonl") == [
        {"id": "Q0001", "candidatos": candidatos_para_dict(esperada)},
    ]
    assert indice.fechado


def test_mistura_busca_no_indice_so_a_pendente_sem_lista_gravada(cenario):
    gravar_reparo_anterior(cenario, {"Q0001": GRAVADA})
    indice = IndiceFalso({**RESPOSTAS_INDICE, "nada novo": [(4697, 0.6)]})
    classificadores = (
        ClassificadorFalso("openai", {TEXTOS["Q0001"]: voto(5548), TEXTOS["Q0005"]: voto(4697)}),
        ClassificadorFalso("anthropic", {TEXTOS["Q0001"]: voto(5548), TEXTOS["Q0005"]: voto(4697)}),
    )
    _, criados = rodar(cenario, classificadores, indice)

    assert criados == ["Tema"]
    # Os dois votos nulos da Q0005 buscam; a justificativa da Q0001 não vai ao índice.
    assert indice.buscas == [("nada novo", reparo.K_REPARO)] * 2
    nova = ORIGINAIS + [Candidato(4697, "reparo", 0.6)]
    for clf in classificadores:
        assert clf.recebidos == [(TEXTOS["Q0001"], GRAVADA), (TEXTOS["Q0005"], nova)]
    linhas = ler_jsonl(cenario / "votos_llm_questoes.jsonl")
    assert linhas[0]["reparo"] == {"novos": [5543, 5548], "revotado": True}
    assert linhas[4]["reparo"] == {"novos": [4697], "revotado": True}
    assert ler_jsonl(cenario / "candidatos_questoes_reparo.jsonl") == [
        {"id": "Q0001", "candidatos": candidatos_para_dict(GRAVADA)},
        {"id": "Q0005", "candidatos": candidatos_para_dict(nova)},
    ]
    assert indice.fechado


def test_recalcular_ignora_a_lista_gravada_e_busca_de_novo(cenario):
    gravar_reparo_anterior(cenario, {"Q0001": GRAVADA})
    indice = IndiceFalso(RESPOSTAS_INDICE)
    classificadores = classificadores_falsos()
    rodar(cenario, classificadores, indice, recalcular=True)

    assert ("porte ilegal de arma de fogo", reparo.K_REPARO) in indice.buscas
    esperada = ORIGINAIS + [Candidato(4697, "reparo", 0.8)]
    for clf in classificadores:
        assert clf.recebidos == [(TEXTOS["Q0001"], esperada)]
    assert ler_jsonl(cenario / "votos_llm_questoes.jsonl")[0]["reparo"] == {"novos": [4697], "revotado": True}
    assert ler_jsonl(cenario / "candidatos_questoes_reparo.jsonl") == [
        {"id": "Q0001", "candidatos": candidatos_para_dict(esperada)},
    ]


def test_sem_pendente_que_precise_de_busca_o_indice_nao_e_montado(cenario):
    so_q0001_pendente(cenario)
    gravar_reparo_anterior(cenario, {"Q0001": GRAVADA})
    classificadores = classificadores_falsos()
    _, criados = rodar(cenario, classificadores, IndiceFalso(RESPOSTAS_INDICE))

    assert criados == []
    assert [clf.chamadas for clf in classificadores] == [1, 1]


def test_votos_regravados_pelo_cache_repetem_o_reparo_mesmo_com_outro_indice(cenario):
    """`classificar tudo` regrava os votos sem a chave reparo; o reparo seguinte não pode depender do índice."""
    rodar(cenario, classificadores_falsos(), IndiceFalso(RESPOSTAS_INDICE))
    votos_antes = ler_jsonl(cenario / "votos_llm_questoes.jsonl")
    candidatos_antes = ler_jsonl(cenario / "candidatos_questoes_reparo.jsonl")

    escrever_jsonl(cenario / "votos_llm_questoes.jsonl", VOTOS_ORIGINAIS)
    # Outro índice (Weaviate no lugar da memória, ou o contrário) poria outro tema no fim da lista ampliada.
    outro = IndiceFalso({**RESPOSTAS_INDICE, "porte ilegal de arma de fogo": [(5548, 0.8)]})
    classificadores = classificadores_falsos()
    rodar(cenario, classificadores, outro)

    for clf in classificadores:
        assert clf.recebidos == [(TEXTOS["Q0001"], ORIGINAIS + [Candidato(4697, "reparo", 0.8)])]
    assert ("porte ilegal de arma de fogo", reparo.K_REPARO) not in outro.buscas
    assert ler_jsonl(cenario / "votos_llm_questoes.jsonl") == votos_antes
    assert ler_jsonl(cenario / "candidatos_questoes_reparo.jsonl") == candidatos_antes


# --- pipeline e CLI --------------------------------------------------------------------------------------


def test_reparo_vem_logo_depois_dos_votos_no_tudo():
    nomes = [nome for nome, _ in pipeline.ETAPAS_TUDO]
    assert nomes[nomes.index("votos questoes") + 1] == "reparo questoes"
    assert nomes[nomes.index("votos corpus") + 1] == "reparo corpus"
    assert nomes.index("reparo corpus") < nomes.index("vizinhanca questoes")


def test_reparo_no_tudo_repassa_recalcular(monkeypatch, tmp_path):
    recebido = []
    monkeypatch.setattr(pipeline, "etapa_reparar", lambda alvo, recalcular=False: recebido.append((alvo, recalcular)))
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("", encoding="utf-8")
    monkeypatch.setattr(pipeline, "caminho_corpus", lambda: corpus)
    etapas = [(nome, funcao) for nome, funcao in pipeline.ETAPAS_TUDO if nome.startswith("reparo")]
    pipeline.rodar_tudo(etapas)
    pipeline.rodar_tudo(etapas, recalcular=True)
    assert recebido == [("questoes", False), ("corpus", False), ("questoes", True), ("corpus", True)]


def test_main_reparar_despacha(monkeypatch):
    recebido = []
    monkeypatch.setattr(pipeline, "etapa_reparar", lambda alvo, recalcular=False: recebido.append((alvo, recalcular)))
    pipeline.main(["reparar"])
    pipeline.main(["reparar", "--alvo", "corpus", "--recalcular"])
    assert recebido == [("questoes", False), ("corpus", True)]


def test_reparar_help(capsys):
    with pytest.raises(SystemExit) as saida:
        pipeline.main(["reparar", "--help"])
    assert saida.value.code == 0
    texto = capsys.readouterr().out
    assert "--alvo" in texto
    assert "--recalcular" in texto


def test_reparo_registra_etapa_e_questao_no_contexto_de_custos(cenario):
    from classificador import custos

    vistos = {"indice": [], "busca": [], "classificar": []}

    class ClassificadorAnotador(ClassificadorFalso):
        def classificar(self, texto, candidatos, arvore):
            vistos["classificar"].append(custos.contexto_atual())
            return super().classificar(texto, candidatos, arvore)

    class IndiceAnotador(IndiceFalso):
        def buscar(self, texto, k, excluir=frozenset()):
            vistos["busca"].append(custos.contexto_atual())
            return super().buscar(texto, k, excluir)

    indice = IndiceAnotador(RESPOSTAS_INDICE)

    def criar(nome, embeddings):
        vistos["indice"].append(custos.contexto_atual())
        return indice

    classificadores = (
        ClassificadorAnotador("openai", {TEXTOS["Q0001"]: voto(4697)}),
        ClassificadorAnotador("anthropic", {TEXTOS["Q0001"]: voto(4697)}),
    )
    rodar_reparo("questoes", ArvoreTemas.carregar(), EmbeddingsFalsas(), classificadores, pasta=cenario, criar=criar)
    assert vistos["indice"] == [custos.Contexto("reparo", "questoes", None)]
    assert vistos["classificar"] == [custos.Contexto("reparo", "questoes", "Q0001")] * 2
    assert {c.id_questao for c in vistos["busca"]} == {"Q0001", "Q0005"}
    assert {c.etapa for c in vistos["busca"]} == {"reparo"}
    assert custos.contexto_atual() == custos.Contexto()
