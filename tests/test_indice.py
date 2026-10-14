import os

import pytest

from classificador import indice as modulo
from classificador.indice import IndiceMemoria, Resultado, criar_indice
from tests.fakes import EmbeddingsFalsas


def _popular(ind):
    ind.adicionar(
        ["a", "b", "c"],
        ["furto de coisa alheia móvel", "roubo com violência", "prescrição da pretensão punitiva"],
        [{"tema_id": 5159}, {"tema_id": 5160}, {"tema_id": 5188}],
    )


def _contrato(ind):
    _popular(ind)
    assert ind.tamanho() == 3
    resultados = ind.buscar("furto de coisa alheia móvel", k=2)
    assert len(resultados) == 2
    assert isinstance(resultados[0], Resultado)
    assert resultados[0].id == "a"
    assert resultados[0].metadados == {"tema_id": 5159}
    assert resultados[0].similaridade == pytest.approx(1.0, abs=1e-6)
    assert resultados[0].similaridade >= resultados[1].similaridade
    sem_a = ind.buscar("furto de coisa alheia móvel", k=2, excluir=frozenset({"a"}))
    assert [r.id for r in sem_a] == [r.id for r in ind.buscar("furto de coisa alheia móvel", k=3)][1:3]
    assert len(ind.buscar("x", k=10)) == 3


def test_indice_memoria_cumpre_o_contrato():
    _contrato(IndiceMemoria("Teste", EmbeddingsFalsas()))


def test_indice_memoria_vazio_devolve_lista_vazia():
    ind = IndiceMemoria("Teste", EmbeddingsFalsas())
    assert ind.tamanho() == 0
    assert ind.buscar("x", k=3) == []


def test_criar_indice_cai_para_memoria_quando_desligado(monkeypatch):
    monkeypatch.setenv("USAR_WEAVIATE", "nao")
    ind = criar_indice("Teste", EmbeddingsFalsas())
    assert isinstance(ind, IndiceMemoria)


def test_criar_indice_cai_para_memoria_quando_weaviate_nao_responde(monkeypatch):
    monkeypatch.setenv("USAR_WEAVIATE", "auto")
    monkeypatch.setenv("WEAVIATE_URL", "http://localhost:1")
    ind = criar_indice("Teste", EmbeddingsFalsas())
    assert isinstance(ind, IndiceMemoria)


def test_criar_indice_exige_weaviate_quando_obrigatorio(monkeypatch):
    monkeypatch.setenv("USAR_WEAVIATE", "sim")
    monkeypatch.setenv("WEAVIATE_URL", "http://localhost:1")
    with pytest.raises(Exception):
        criar_indice("Teste", EmbeddingsFalsas())


@pytest.mark.skipif(os.environ.get("WEAVIATE_TESTE") != "1", reason="exige Weaviate local; rode com WEAVIATE_TESTE=1")
def test_indice_weaviate_cumpre_o_contrato(monkeypatch):
    monkeypatch.setenv("USAR_WEAVIATE", "sim")
    cliente = modulo.conectar_weaviate()
    ind = modulo.IndiceWeaviate("TesteContrato", EmbeddingsFalsas(), cliente)
    try:
        _contrato(ind)
    finally:
        ind.fechar()
