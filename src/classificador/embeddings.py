"""Embeddings da OpenAI via LangChain, com cache em disco por texto."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from langchain_core.embeddings import Embeddings

from classificador.config import CAMINHOS, ChaveAusenteError, ler_env

MODELO_PADRAO = "text-embedding-3-large"


class EmbeddingsComCache(Embeddings):
    """Lê do cache o que já foi calculado; chama a base só para o que falta."""

    def __init__(self, base: Embeddings | None, modelo: str, pasta_cache: Path) -> None:
        self.base = base
        self.modelo = modelo
        self.pasta = pasta_cache / "embeddings" / modelo
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.chamadas_base = 0
        self.acertos_cache = 0

    def _arquivo(self, texto: str) -> Path:
        chave = hashlib.sha256(f"{self.modelo}\n{texto}".encode("utf-8")).hexdigest()
        return self.pasta / f"{chave}.json"

    def _ler(self, texto: str) -> list[float] | None:
        arquivo = self._arquivo(texto)
        if not arquivo.exists():
            return None
        try:
            vetor = json.loads(arquivo.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            arquivo.unlink()
            return None
        if not isinstance(vetor, list) or not vetor or not all(isinstance(x, (int, float)) for x in vetor):
            arquivo.unlink()
            return None
        return [float(x) for x in vetor]

    def _gravar(self, texto: str, vetor: list[float]) -> None:
        self._arquivo(texto).write_text(json.dumps(vetor), encoding="utf-8")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        resultado: list[list[float] | None] = [self._ler(t) for t in texts]
        self.acertos_cache += sum(1 for v in resultado if v is not None)
        faltantes = [i for i, v in enumerate(resultado) if v is None]
        if faltantes:
            if self.base is None:
                raise ChaveAusenteError(
                    f"{len(faltantes)} texto(s) sem embedding em cache e OPENAI_API_KEY ausente. "
                    "Defina a chave no .env ou use o cache commitado."
                )
            novos = self.base.embed_documents([texts[i] for i in faltantes])
            self.chamadas_base += len(faltantes)
            for indice, vetor in zip(faltantes, novos):
                vetor = [float(x) for x in vetor]
                self._gravar(texts[indice], vetor)
                resultado[indice] = vetor
        return [v for v in resultado if v is not None]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def criar_embeddings(pasta_cache: Path = CAMINHOS.cache) -> EmbeddingsComCache:
    modelo = ler_env("MODELO_EMBEDDINGS", MODELO_PADRAO) or MODELO_PADRAO
    base: Embeddings | None = None
    if ler_env("OPENAI_API_KEY"):
        from langchain_openai import OpenAIEmbeddings

        base = OpenAIEmbeddings(model=modelo)
    return EmbeddingsComCache(base, modelo, pasta_cache)
