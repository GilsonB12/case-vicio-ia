import json

import pytest
from langchain_core.embeddings import Embeddings

from classificador.arvore import ArvoreTemas
from classificador.dados import carregar_corpus, carregar_questoes, montar_texto
from scripts.consolidar_corpus import consolidar, main, normalizar_texto
from tests.fakes import EmbeddingsFalsas, vetor_falso

ENUNCIADO_LONGO = "Sobre a Lei Maria da Penha, considere a situação descrita a seguir e responda."


def linha(enunciado: str = ENUNCIADO_LONGO, **campos) -> dict:
    base = {
        "tema_id": 4704,
        "enunciado": enunciado,
        "comando": "Assinale a alternativa correta.",
        "alternativas": {"A": "Primeira opção", "B": "Segunda opção"},
        "url": "https://exemplo.gov.br/prova.pdf",
        "site": "exemplo.gov.br",
        "banca_ano": "FGV 2023",
        "confianca_fonte": "alta",
        "gabarito": "A",
    }
    base.update(campos)
    return base


def gravar_lote(pasta, nome: str, linhas: list) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / f"lote-{nome}.jsonl", "w", encoding="utf-8") as arquivo:
        for item in linhas:
            texto = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            arquivo.write(texto + "\n")


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


@pytest.fixture(scope="module")
def questoes_case():
    return carregar_questoes()


@pytest.fixture
def caminhos(tmp_path):
    return tmp_path / "coleta", tmp_path / "corpus.jsonl", tmp_path / "resumo.json"


def ler_saida(saida) -> list[dict]:
    return [json.loads(l) for l in saida.read_text(encoding="utf-8").splitlines() if l.strip()]


def motivos(resumo: dict) -> list[str]:
    return [d["motivo"] for d in resumo["descartadas"]]


# Esquema


def test_linha_malformada_e_descartada_por_schema_e_o_resto_segue(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", [
        '{"tema_id": 4704, "enunciado": "quebrado',
        linha(),
        linha(enunciado=ENUNCIADO_LONGO + " Segunda questão."),
    ])
    resumo = consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    assert motivos(resumo) == ["schema"]
    assert resumo["descartadas"][0]["linha"] == 1
    assert len(ler_saida(saida)) == 2


@pytest.mark.parametrize("defeito", [
    {"tema_id": "4704"},
    {"tema_id": True},
    {"alternativas": {}},
    {"alternativas": ["A", "B"]},
    {"alternativas": {"A": 1}},
    {"confianca_fonte": "altissima"},
    {"url": None},
    {"enunciado": None},
])
def test_campo_com_tipo_errado_e_descartado_por_schema(caminhos, arvore, defeito):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", [linha(**defeito)])
    resumo = consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    assert motivos(resumo) == ["schema"]
    assert ler_saida(saida) == []


def test_campos_opcionais_nulos_viram_vazio(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", [linha(comando=None, gabarito=None, banca_ano=None)])
    resumo = consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    assert resumo["descartadas"] == []
    [questao] = ler_saida(saida)
    assert (questao["comando"], questao["gabarito"], questao["banca_ano"]) == ("", "", "")


def test_campo_ausente_e_linha_que_nao_e_objeto_sao_schema(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    sem_url = linha()
    del sem_url["url"]
    gravar_lote(pasta, "01", [sem_url, "[1, 2, 3]"])
    resumo = consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    assert motivos(resumo) == ["schema", "schema"]


def test_linhas_em_branco_nao_contam_como_lidas(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", ["", linha(), "   "])
    resumo = consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    assert resumo["lotes"]["01"]["lidas"] == 1


# Tema


def test_tema_duplicado_e_canonicalizado(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", [linha(tema_id=6724)])
    consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    assert [q["tema_id"] for q in ler_saida(saida)] == [4704]


def test_tema_inativo_inexistente_ou_raiz_e_descartado(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", [
        linha(tema_id=5078),
        linha(tema_id=999999, enunciado=ENUNCIADO_LONGO + " B"),
        linha(tema_id=4365, enunciado=ENUNCIADO_LONGO + " C"),
    ])
    resumo = consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    assert motivos(resumo) == ["tema_nao_publicavel"] * 3
    assert ler_saida(saida) == []


# Texto


def test_enunciado_curto_sem_html_e_descartado(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    curto_com_tags = "<p><b>" + "x" * 39 + "</b></p>" + "<br>" * 10
    gravar_lote(pasta, "01", [linha(enunciado=curto_com_tags), linha(enunciado="y" * 40)])
    resumo = consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    assert motivos(resumo) == ["enunciado_curto"]
    assert len(ler_saida(saida)) == 1


def test_normalizar_texto_ignora_caixa_acento_e_espacos():
    assert normalizar_texto("  Ação   PENAL\n pública ") == "acao penal publica"


def test_duplicata_de_texto_mantem_a_primeira_ocorrencia(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", [linha(url="https://primeira")])
    gravar_lote(pasta, "02", [
        linha(
            enunciado="<p>" + ENUNCIADO_LONGO.upper().replace("SITUAÇÃO", "SITUACAO") + "</p>",
            alternativas={"A": "  primeira   opcao ", "B": "SEGUNDA OPÇÃO"},
            url="https://segunda",
        ),
    ])
    resumo = consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    assert motivos(resumo) == ["duplicata_texto"]
    assert resumo["descartadas"][0]["lote"] == "02"
    assert [q["url"] for q in ler_saida(saida)] == ["https://primeira"]


# Embeddings


def test_questao_igual_a_uma_do_case_e_descartada(caminhos, arvore, questoes_case):
    pasta, saida, resumo_caminho = caminhos
    q1 = questoes_case.iloc[0]
    assert q1["id"] == "Q0001"
    copia = linha(enunciado=q1["enunciado_html"], comando=q1["comando"], alternativas=dict(q1["alternativas"]))
    assert montar_texto(copia["enunciado"], copia["comando"], copia["alternativas"]) == q1["texto"]
    gravar_lote(pasta, "01", [linha(), copia])
    resumo = consolidar(
        pasta, saida, resumo_caminho, embeddings=EmbeddingsFalsas(), arvore=arvore, questoes_case=questoes_case
    )
    assert motivos(resumo) == ["igual_a_questao_do_case"]
    assert resumo["descartadas"][0]["referencia"] == "Q0001"
    assert len(ler_saida(saida)) == 1


class EmbeddingsDoInicio(Embeddings):
    """Textos com o mesmo início dão o mesmo vetor, para simular paráfrases próximas."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vetor_falso(t[:60]) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return vetor_falso(text[:60])


def test_duplicata_por_embedding_mantem_a_primeira(caminhos, arvore, questoes_case):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", [
        linha(url="https://primeira"),
        linha(alternativas={"A": "Outra redação", "B": "Mais uma"}, url="https://segunda"),
    ])
    resumo = consolidar(
        pasta, saida, resumo_caminho, embeddings=EmbeddingsDoInicio(), arvore=arvore, questoes_case=questoes_case
    )
    assert motivos(resumo) == ["duplicata_embedding"]
    assert [q["url"] for q in ler_saida(saida)] == ["https://primeira"]


def test_sem_embeddings_nao_compara_com_o_case(caminhos, arvore, questoes_case):
    pasta, saida, resumo_caminho = caminhos
    q1 = questoes_case.iloc[0]
    gravar_lote(pasta, "01", [
        linha(enunciado=q1["enunciado_html"], comando=q1["comando"], alternativas=dict(q1["alternativas"])),
    ])
    resumo = consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    assert resumo["embeddings"] is False
    assert len(ler_saida(saida)) == 1


# Saída


def test_ids_sequenciais_na_ordem_dos_lotes(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "piloto", [linha(enunciado=ENUNCIADO_LONGO + " piloto")])
    gravar_lote(pasta, "02", [linha(enunciado=ENUNCIADO_LONGO + " dois a"), linha(enunciado=ENUNCIADO_LONGO + " dois b")])
    gravar_lote(pasta, "01", [linha(enunciado=ENUNCIADO_LONGO + " um")])
    consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    corpus = ler_saida(saida)
    assert [q["id"] for q in corpus] == ["C0001", "C0002", "C0003", "C0004"]
    assert [q["lote"] for q in corpus] == ["01", "02", "02", "piloto"]
    assert corpus[1]["enunciado"].endswith("dois a")
    assert set(corpus[0]) == {
        "id", "tema_id", "enunciado", "comando", "alternativas", "url", "site",
        "banca_ano", "confianca_fonte", "gabarito", "lote",
    }


def test_resumo_tem_as_chaves_esperadas(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", [
        linha(),
        linha(enunciado=ENUNCIADO_LONGO + " outra", tema_id=5159, confianca_fonte="media"),
        linha(tema_id=5078, enunciado=ENUNCIADO_LONGO + " inativo"),
        "nao e json",
    ])
    consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    resumo = json.loads(resumo_caminho.read_text(encoding="utf-8"))
    assert {"lotes", "total_lidas", "total_mantidas", "descartadas_por_motivo", "por_tema",
            "por_confianca", "descartadas", "embeddings"} <= set(resumo)
    assert resumo["lotes"]["01"] == {
        "lidas": 4, "mantidas": 2, "descartadas": {"schema": 1, "tema_nao_publicavel": 1},
    }
    assert resumo["total_mantidas"] == 2
    assert resumo["por_tema"] == {"4704": 1, "5159": 1}
    assert resumo["por_confianca"] == {"alta": 1, "media": 1, "baixa": 0}
    descartada = next(d for d in resumo["descartadas"] if d["motivo"] == "tema_nao_publicavel")
    assert descartada["trecho"] == ENUNCIADO_LONGO[:60]
    assert {"lote", "linha", "motivo", "trecho"} <= set(descartada)


def test_carregar_corpus_le_a_saida_e_monta_texto(caminhos, arvore):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", [linha(tema_id=6724)])
    consolidar(pasta, saida, resumo_caminho, arvore=arvore)
    df = carregar_corpus(saida)
    assert df.loc[0, "id"] == "C0001"
    assert df.loc[0, "tema_id"] == 4704
    assert df.loc[0, "texto"].startswith(ENUNCIADO_LONGO)
    assert "Alternativas:\nA) Primeira opção" in df.loc[0, "texto"]


# CLI


def test_cli_sem_embeddings_grava_saida_e_retorna_zero(caminhos, capsys):
    pasta, saida, resumo_caminho = caminhos
    gravar_lote(pasta, "01", [linha(), "{malformada"])
    codigo = main([
        "--pasta", str(pasta), "--saida", str(saida), "--resumo", str(resumo_caminho), "--sem-embeddings",
    ])
    assert codigo == 0
    assert len(ler_saida(saida)) == 1
    assert resumo_caminho.exists()
    assert "mantidas" in capsys.readouterr().out


def test_cli_sem_arquivos_de_entrada_retorna_erro(caminhos):
    pasta, saida, resumo_caminho = caminhos
    pasta.mkdir()
    codigo = main([
        "--pasta", str(pasta), "--saida", str(saida), "--resumo", str(resumo_caminho), "--sem-embeddings",
    ])
    assert codigo != 0
    assert not saida.exists()
