"""Índice vetorial: Weaviate em Docker, com índice em memória como substituto."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import numpy as np
from langchain_core.embeddings import Embeddings

from classificador.config import ler_env

registro = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resultado:
    id: str
    metadados: dict
    similaridade: float


class Indice(Protocol):
    nome: str

    def adicionar(self, ids: list[str], textos: list[str], metadados: list[dict]) -> None: ...

    def buscar(self, texto: str, k: int, excluir: frozenset[str] = frozenset()) -> list[Resultado]: ...

    def tamanho(self) -> int: ...

    def fechar(self) -> None: ...


def _normalizar(matriz: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return matriz / normas


class IndiceMemoria:
    """Busca por cosseno com NumPy. Serve para testes e para rodar sem Docker."""

    def __init__(self, nome: str, embeddings: Embeddings) -> None:
        self.nome = nome
        self._embeddings = embeddings
        self._ids: list[str] = []
        self._metadados: list[dict] = []
        self._vetores: np.ndarray | None = None

    def adicionar(self, ids: list[str], textos: list[str], metadados: list[dict]) -> None:
        if not ids:
            return
        novos = _normalizar(np.asarray(self._embeddings.embed_documents(textos), dtype=np.float64))
        self._vetores = novos if self._vetores is None else np.vstack([self._vetores, novos])
        self._ids.extend(ids)
        self._metadados.extend(metadados)

    def buscar(self, texto: str, k: int, excluir: frozenset[str] = frozenset()) -> list[Resultado]:
        if self._vetores is None or k <= 0:
            return []
        consulta = _normalizar(np.asarray([self._embeddings.embed_query(texto)], dtype=np.float64))[0]
        similaridades = self._vetores @ consulta
        ordem = np.argsort(-similaridades, kind="stable")
        resultados: list[Resultado] = []
        for posicao in ordem:
            if self._ids[posicao] in excluir:
                continue
            resultados.append(Resultado(self._ids[posicao], dict(self._metadados[posicao]), float(similaridades[posicao])))
            if len(resultados) == k:
                break
        return resultados

    def tamanho(self) -> int:
        return len(self._ids)

    def fechar(self) -> None:
        """Nada a liberar: existe para cumprir o contrato do Indice."""


class IndiceWeaviate:
    """Coleção no Weaviate com vetores fornecidos por nós (sem vetorizador do servidor)."""

    def __init__(self, nome: str, embeddings: Embeddings, cliente) -> None:
        from weaviate.classes.config import Configure, DataType, Property

        self.nome = nome
        self._embeddings = embeddings
        self._cliente = cliente
        if cliente.collections.exists(nome):
            cliente.collections.delete(nome)
        propriedades = [
            Property(name="id_externo", data_type=DataType.TEXT),
            Property(name="metadados_json", data_type=DataType.TEXT),
        ]
        if hasattr(Configure, "Vectors"):
            # Vetor nomeado: o cliente chama de "default" o vetor criado sem nome.
            self._nome_vetor: str | None = "default"
            self._colecao = cliente.collections.create(
                name=nome, properties=propriedades, vector_config=Configure.Vectors.self_provided()
            )
        else:
            self._nome_vetor = None
            self._colecao = cliente.collections.create(
                name=nome, properties=propriedades, vectorizer_config=Configure.Vectorizer.none()
            )

    def adicionar(self, ids: list[str], textos: list[str], metadados: list[dict]) -> None:
        if not ids:
            return
        vetores = self._embeddings.embed_documents(textos)
        with self._colecao.batch.dynamic() as lote:
            for id_externo, meta, vetor in zip(ids, metadados, vetores):
                lote.add_object(
                    properties={"id_externo": id_externo, "metadados_json": json.dumps(meta, ensure_ascii=False)},
                    # O Weaviate 1.27 guarda uma lista solta sem indexá-la no vetor nomeado; a busca não a acharia.
                    vector=vetor if self._nome_vetor is None else {self._nome_vetor: vetor},
                )
        falhas = self._colecao.batch.failed_objects
        if falhas:
            raise RuntimeError(f"Weaviate recusou {len(falhas)} objeto(s) na coleção {self.nome}: {falhas[0]}")

    def buscar(self, texto: str, k: int, excluir: frozenset[str] = frozenset()) -> list[Resultado]:
        from weaviate.classes.query import MetadataQuery

        if k <= 0 or self.tamanho() == 0:
            return []
        vetor = self._embeddings.embed_query(texto)
        resposta = self._colecao.query.near_vector(
            near_vector=vetor,
            limit=k + len(excluir),
            return_metadata=MetadataQuery(distance=True),
            return_properties=["id_externo", "metadados_json"],
        )
        resultados: list[Resultado] = []
        for objeto in resposta.objects:
            id_externo = str(objeto.properties["id_externo"])
            if id_externo in excluir:
                continue
            metadados = json.loads(objeto.properties["metadados_json"])
            resultados.append(Resultado(id_externo, metadados, 1.0 - float(objeto.metadata.distance)))
            if len(resultados) == k:
                break
        return resultados

    def tamanho(self) -> int:
        return int(self._colecao.aggregate.over_all(total_count=True).total_count or 0)

    def fechar(self) -> None:
        self._cliente.close()


def conectar_weaviate():
    modo = (ler_env("USAR_WEAVIATE", "auto") or "auto").lower()
    if modo == "nao":
        return None
    url = urlparse(ler_env("WEAVIATE_URL", "http://localhost:8080") or "http://localhost:8080")
    try:
        import weaviate
        from weaviate.classes.init import AdditionalConfig, Timeout

        cliente = weaviate.connect_to_local(
            host=url.hostname or "localhost",
            port=url.port or 8080,
            grpc_port=50051,
            additional_config=AdditionalConfig(timeout=Timeout(init=5, query=30, insert=120)),
        )
        if not cliente.is_ready():
            cliente.close()
            raise ConnectionError("Weaviate respondeu mas não está pronto")
        return cliente
    except Exception as erro:
        if modo == "sim":
            raise
        registro.warning("Weaviate indisponível (%s); usando índice em memória.", erro)
        return None


def criar_indice(nome: str, embeddings: Embeddings) -> Indice:
    cliente = conectar_weaviate()
    if cliente is None:
        return IndiceMemoria(nome, embeddings)
    return IndiceWeaviate(nome, embeddings, cliente)
