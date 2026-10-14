import pandas as pd
import pytest

from classificador import vizinhanca as modulo
from classificador.arvore import ArvoreTemas
from classificador.candidatos import montar_indice_corpus
from classificador.dados import ler_jsonl
from classificador.indice import IndiceMemoria
from classificador.vizinhanca import VotoVizinhanca, votar_vizinhanca
from tests.fakes import EmbeddingsFalsas


def criar_memoria(nome, embeddings):
    return IndiceMemoria(nome, embeddings)


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def indice_com(arvore, linhas):
    corpus = pd.DataFrame(linhas)
    return montar_indice_corpus(corpus, arvore, EmbeddingsFalsas(), criar=criar_memoria)


def test_vizinhos_votam_nos_dois_niveis(arvore):
    indice = indice_com(arvore, [
        {"id": "C1", "tema_id": 5527, "texto": "pronuncia e impronuncia no juri"},
        {"id": "C2", "tema_id": 5527, "texto": "desclassificacao pelo juiz sumariante"},
        {"id": "C3", "tema_id": 5528, "texto": "sessao de julgamento do juri"},
    ])
    voto = votar_vizinhanca("pronuncia e impronuncia no juri", indice, arvore, k=3)
    assert voto.tema_nivel1 == 5524
    assert voto.peso_nivel1 == pytest.approx(1.0)
    assert voto.tema_nivel2 in {5527, 5528}
    assert 0 < voto.peso_nivel2 <= 1.0
    assert voto.vizinhos[0].id == "C1"
    assert voto.vizinhos[0].similaridade == pytest.approx(1.0, abs=1e-6)


def test_vizinho_de_nivel1_vota_so_no_nivel1(arvore):
    indice = indice_com(arvore, [{"id": "C1", "tema_id": 5524, "texto": "texto"}])
    voto = votar_vizinhanca("texto", indice, arvore)
    assert voto.tema_nivel1 == 5524 and voto.peso_nivel1 == pytest.approx(1.0)
    assert voto.tema_nivel2 is None and voto.peso_nivel2 == 0.0


def test_tema_duplicado_no_corpus_e_canonicalizado(arvore):
    indice = indice_com(arvore, [{"id": "C1", "tema_id": 6724, "texto": "texto"}])
    voto = votar_vizinhanca("texto", indice, arvore)
    assert voto.tema_nivel1 == 4704
    assert voto.vizinhos[0].tema_id == 4704


def test_corpus_vazio_e_exclusao_devolvem_voto_nulo(arvore):
    vazio = indice_com(arvore, [])
    nulo = votar_vizinhanca("texto", vazio, arvore)
    assert nulo == VotoVizinhanca(None, 0.0, None, 0.0, [])
    um = indice_com(arvore, [{"id": "C1", "tema_id": 5524, "texto": "texto"}])
    assert votar_vizinhanca("texto", um, arvore, excluir=frozenset({"C1"})).tema_nivel1 is None


def test_ida_e_volta_dict(arvore):
    indice = indice_com(arvore, [{"id": "C1", "tema_id": 5527, "texto": "texto"}])
    voto = votar_vizinhanca("texto", indice, arvore)
    assert VotoVizinhanca.de_dict(voto.para_dict()) == voto


def test_rodar_sem_corpus_grava_votos_nulos(arvore, tmp_path):
    saida = modulo.rodar_vizinhanca(
        "questoes", arvore, EmbeddingsFalsas(), pasta_saida=tmp_path,
        caminho_corpus=tmp_path / "nao_existe.jsonl", criar=criar_memoria,
    )
    linhas = ler_jsonl(saida)
    assert len(linhas) == 359
    assert linhas[0]["tema_nivel1"] is None and linhas[0]["vizinhos"] == []
