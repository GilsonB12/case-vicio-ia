import json

import pandas as pd
import pytest

from classificador import candidatos as modulo
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato, buscar_candidatos, montar_indice_corpus, montar_indice_temas
from classificador.dados import ler_jsonl
from classificador.indice import IndiceMemoria
from tests.fakes import EmbeddingsFalsas


def criar_memoria(nome, embeddings):
    return IndiceMemoria(nome, embeddings)


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


@pytest.fixture(scope="module")
def indice_temas(arvore):
    return montar_indice_temas(arvore, EmbeddingsFalsas(), criar=criar_memoria)


def test_indice_de_temas_tem_um_documento_por_tema_publicavel(arvore, indice_temas):
    assert indice_temas.tamanho() == len(arvore.candidatos_possiveis())


def test_candidatos_respeitam_teto_pais_e_ordem(arvore, indice_temas):
    lista = buscar_candidatos("qualquer texto de questão", indice_temas, arvore)
    assert 0 < len(lista) <= modulo.TETO
    ids = [c.tema_id for c in lista]
    assert len(ids) == len(set(ids))
    for c in lista:
        assert arvore.publicavel(c.tema_id)
        if arvore.nivel(c.tema_id) == 2:
            pai = arvore.pai(c.tema_id)
            assert pai in ids
            assert ids.index(pai) < ids.index(c.tema_id)
    similaridades = [c.similaridade for c in lista]
    assert similaridades == sorted(similaridades, reverse=True)


def test_vizinho_do_corpus_vira_candidato_com_origem_corpus(arvore, indice_temas):
    corpus = pd.DataFrame([{
        "id": "C0001", "tema_id": 6724, "texto": "texto identico ao da consulta",
    }])
    indice_corpus = montar_indice_corpus(corpus, arvore, EmbeddingsFalsas(), criar=criar_memoria)
    # k_temas=0 isola a fonte corpus: com embeddings falsos, o tema poderia vir por acaso do índice de temas.
    lista = buscar_candidatos("texto identico ao da consulta", indice_temas, arvore, indice_corpus, k_temas=0)
    por_id = {c.tema_id: c for c in lista}
    assert 4704 in por_id
    assert por_id[4704].origem == "corpus"
    assert por_id[4704].similaridade == pytest.approx(1.0, abs=1e-6)


def test_excluir_corpus_tira_a_propria_questao(arvore, indice_temas):
    corpus = pd.DataFrame([{"id": "C0001", "tema_id": 5527, "texto": "texto identico ao da consulta"}])
    indice_corpus = montar_indice_corpus(corpus, arvore, EmbeddingsFalsas(), criar=criar_memoria)
    lista = buscar_candidatos(
        "texto identico ao da consulta", indice_temas, arvore, indice_corpus, excluir_corpus=frozenset({"C0001"})
    )
    assert all(c.origem != "corpus" for c in lista)


def test_ida_e_volta_para_dict():
    lista = [Candidato(5527, "tema", 0.5)]
    assert modulo.candidatos_de_dict(modulo.candidatos_para_dict(lista)) == lista


def test_rodar_candidatos_passada_1_grava_jsonl_e_temas_alvo(arvore, tmp_path):
    saida = modulo.rodar_candidatos("questoes", 1, arvore, EmbeddingsFalsas(), pasta_saida=tmp_path, criar=criar_memoria)
    linhas = ler_jsonl(saida)
    assert len(linhas) == 359
    assert set(linhas[0]) == {"id", "candidatos"}
    alvo = json.loads((tmp_path / "temas_alvo_corpus.json").read_text(encoding="utf-8"))
    assert alvo == sorted(alvo)
    assert all(arvore.publicavel(t) for t in alvo)
    for linha in linhas:
        for c in linha["candidatos"]:
            assert c["tema_id"] in alvo
            if arvore.nivel(c["tema_id"]) == 2:
                assert arvore.pai(c["tema_id"]) in alvo
