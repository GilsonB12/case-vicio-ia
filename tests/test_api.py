"""API: rotas com o serviço trocado por um dublê e a carga preguiçosa do serviço real."""
import pytest
from fastapi.testclient import TestClient

import api.main
import api.servico
from classificador.config import ChaveAusenteError
from tests.fakes import EmbeddingsFalsas

ENTRADA = {
    "enunciado_html": "<p>Sobre o crime de furto, analise as assertivas.</p>",
    "comando": "Assinale a alternativa correta.",
    "alternativas": {"A": "É crime contra o patrimônio.", "B": "É crime contra a vida."},
}

RESPOSTA = {
    "decisao": "publicar",
    "tema_central_id": 10,
    "caminho": "Penal > Furto",
    "extras_ids": [11],
    "confianca": 0.9,
    "motivo": "",
    "regra": 2,
    "candidatos": [{"tema_id": 10, "caminho": "Penal > Furto", "origem": "tema", "similaridade": 0.8}],
    "votos": {
        "openai": {"tema_central_id": 10, "extras_ids": [11], "disciplina": "Penal", "confianca": 0.9, "justificativa": "Furto."},
        "anthropic": None,
        "vizinhanca": {"tema_nivel2": None, "peso_nivel2": 0.0, "tema_nivel1": None, "peso_nivel1": 0.0, "vizinhos": []},
    },
}

SAUDE = {
    "chaves": {"openai": False, "anthropic": False},
    "weaviate": False,
    "corpus": False,
    "cache_votos": 0,
    "limiares": {"publicar": 0.8, "pai": 0.7, "contradicao": 0.6},
}

TEMAS = [{"tema_id": 10, "caminho": "Penal > Furto", "nivel": 1, "disciplina": "Penal"}]


class ServicoDuble:
    """Faz o papel do Servico sem carregar nada; guarda o que a rota repassou."""

    def __init__(self) -> None:
        self.erro: Exception | None = None
        self.recebido: tuple | None = None

    def classificar(self, enunciado_html: str, comando: str, alternativas: dict[str, str]) -> dict:
        self.recebido = (enunciado_html, comando, alternativas)
        if self.erro is not None:
            raise self.erro
        return RESPOSTA

    def saude(self) -> dict:
        return SAUDE

    def temas(self) -> list[dict]:
        return TEMAS


@pytest.fixture
def duble(monkeypatch):
    substituto = ServicoDuble()
    monkeypatch.setattr(api.main, "servico", substituto)
    return substituto


@pytest.fixture
def cliente():
    return TestClient(api.main.app)


def test_saude_devolve_o_estado_do_servico(duble, cliente):
    resposta = cliente.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json() == SAUDE


def test_temas_devolve_a_lista_do_servico(duble, cliente):
    resposta = cliente.get("/temas")
    assert resposta.status_code == 200
    assert resposta.json() == TEMAS


def test_classificar_repassa_a_questao_e_devolve_a_decisao(duble, cliente):
    resposta = cliente.post("/classificar", json=ENTRADA)
    assert resposta.status_code == 200
    assert resposta.json() == RESPOSTA
    assert duble.recebido == (ENTRADA["enunciado_html"], ENTRADA["comando"], ENTRADA["alternativas"])


def test_classificar_sem_comando_usa_texto_vazio(duble, cliente):
    entrada = {chave: valor for chave, valor in ENTRADA.items() if chave != "comando"}
    resposta = cliente.post("/classificar", json=entrada)
    assert resposta.status_code == 200
    assert duble.recebido == (ENTRADA["enunciado_html"], "", ENTRADA["alternativas"])


def _campos_com_erro(resposta) -> list[str]:
    return [erro["loc"][-1] for erro in resposta.json()["detail"]]


def test_classificar_sem_alternativas_devolve_422_apontando_o_campo(duble, cliente):
    entrada = {chave: valor for chave, valor in ENTRADA.items() if chave != "alternativas"}
    resposta = cliente.post("/classificar", json=entrada)
    assert resposta.status_code == 422
    assert _campos_com_erro(resposta) == ["alternativas"]
    assert duble.recebido is None


def test_classificar_com_comando_nulo_devolve_422_apontando_o_campo(duble, cliente):
    resposta = cliente.post("/classificar", json={**ENTRADA, "comando": None})
    assert resposta.status_code == 422
    assert _campos_com_erro(resposta) == ["comando"]
    assert duble.recebido is None


def test_classificar_sem_chave_devolve_503_com_a_mensagem(duble, cliente):
    duble.erro = ChaveAusenteError("sem chave")
    resposta = cliente.post("/classificar", json=ENTRADA)
    assert resposta.status_code == 503
    assert "sem chave" in resposta.json()["detail"]


def test_temas_do_servico_real_sem_tocar_em_embeddings(monkeypatch):
    monkeypatch.setattr(api.servico, "criar_embeddings", lambda: pytest.fail("temas não deveria criar embeddings"))
    temas = api.servico.Servico().temas()
    assert len(temas) == 351
    assert {tuple(sorted(tema)) for tema in temas} == {("caminho", "disciplina", "nivel", "tema_id")}
    assert len({tema["tema_id"] for tema in temas}) == 351
    assert {tema["nivel"] for tema in temas} <= {1, 2}


def test_embeddings_sao_construidas_uma_vez_e_so_no_primeiro_acesso(monkeypatch):
    construidas: list[EmbeddingsFalsas] = []

    def criar_contando() -> EmbeddingsFalsas:
        construidas.append(EmbeddingsFalsas())
        return construidas[-1]

    monkeypatch.setattr(api.servico, "criar_embeddings", criar_contando)
    servico = api.servico.Servico()
    assert construidas == []
    primeira = servico.embeddings
    segunda = servico.embeddings
    assert len(construidas) == 1
    assert primeira is segunda is construidas[0]
