import json

import pytest

from classificador.config import ChaveAusenteError
from classificador.embeddings import EmbeddingsComCache
from tests.fakes import EmbeddingsFalsas


def test_segunda_chamada_vem_do_cache(tmp_path):
    base = EmbeddingsFalsas()
    emb = EmbeddingsComCache(base, "falso", tmp_path)
    primeira = emb.embed_documents(["a", "b"])
    assert len(base.chamadas) == 2
    segunda = emb.embed_documents(["a", "b"])
    assert len(base.chamadas) == 2
    assert primeira == segunda
    assert emb.acertos_cache == 2


def test_mistura_de_acertos_e_faltas_preserva_ordem(tmp_path):
    base = EmbeddingsFalsas()
    emb = EmbeddingsComCache(base, "falso", tmp_path)
    emb.embed_documents(["b"])
    vetores = emb.embed_documents(["a", "b", "c"])
    assert vetores[0] == base.embed_documents(["a"])[0]
    assert vetores[1] == base.embed_documents(["b"])[0]
    assert vetores[2] == base.embed_documents(["c"])[0]


def test_sem_base_e_sem_cache_levanta_erro_claro(tmp_path):
    emb = EmbeddingsComCache(None, "falso", tmp_path)
    with pytest.raises(ChaveAusenteError, match="OPENAI_API_KEY"):
        emb.embed_query("x")


def test_sem_base_com_cache_funciona(tmp_path):
    EmbeddingsComCache(EmbeddingsFalsas(), "falso", tmp_path).embed_query("x")
    emb = EmbeddingsComCache(None, "falso", tmp_path)
    assert len(emb.embed_query("x")) == 16


def test_cache_corrompido_e_regravado(tmp_path):
    base = EmbeddingsFalsas()
    emb = EmbeddingsComCache(base, "falso", tmp_path)
    emb.embed_query("x")
    arquivo = next((tmp_path / "embeddings" / "falso").glob("*.json"))
    arquivo.write_text("{isso nao e json", encoding="utf-8")
    vetor = emb.embed_query("x")
    assert len(base.chamadas) == 2
    assert json.loads(arquivo.read_text(encoding="utf-8")) == vetor


class BaseQueDevolveMenos(EmbeddingsFalsas):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return super().embed_documents(texts)[:1]


def test_base_que_devolve_menos_vetores_levanta_erro(tmp_path):
    emb = EmbeddingsComCache(BaseQueDevolveMenos(), "falso", tmp_path)
    with pytest.raises(RuntimeError, match=r"1 vetor\(es\) para 2 texto\(s\)"):
        emb.embed_documents(["a", "b"])
    assert not list((tmp_path / "embeddings").rglob("*.json"))
