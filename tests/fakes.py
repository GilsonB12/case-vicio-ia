"""Substitutos determinísticos para testes: nunca chamam API."""
from __future__ import annotations

import hashlib

import numpy as np
from langchain_core.embeddings import Embeddings

DIMENSAO_FALSA = 16


def vetor_falso(texto: str) -> list[float]:
    """Vetor determinístico a partir do SHA-256 do texto, normalizado."""
    resumo = hashlib.sha256(texto.encode("utf-8")).digest()
    bruto = np.frombuffer(resumo[:DIMENSAO_FALSA * 2], dtype=np.uint16).astype(np.float64)
    bruto = bruto - bruto.mean()
    norma = np.linalg.norm(bruto) or 1.0
    return (bruto / norma).tolist()


class EmbeddingsFalsas(Embeddings):
    """Embeddings determinísticos. Textos iguais dão vetores iguais."""

    def __init__(self) -> None:
        self.chamadas: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.chamadas.extend(texts)
        return [vetor_falso(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.chamadas.append(text)
        return vetor_falso(text)
