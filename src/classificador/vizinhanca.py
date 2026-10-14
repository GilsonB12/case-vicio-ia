"""Voto por vizinhança: as questões do corpus mais próximas votam no tema delas."""
from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from langchain_core.embeddings import Embeddings

from classificador.arvore import ArvoreTemas
from classificador.candidatos import montar_indice_corpus
from classificador.config import CAMINHOS
from classificador.dados import carregar_corpus, carregar_questoes, escrever_jsonl
from classificador.embeddings import criar_embeddings
from classificador.indice import Indice, criar_indice

registro = logging.getLogger(__name__)

K_VIZINHOS = 10
COLUNAS_CORPUS = ["id", "tema_id", "enunciado", "comando", "alternativas", "url", "site", "confianca_fonte", "texto"]


@dataclass(frozen=True)
class Vizinho:
    id: str
    tema_id: int
    similaridade: float


@dataclass(frozen=True)
class VotoVizinhanca:
    tema_nivel2: int | None
    peso_nivel2: float
    tema_nivel1: int | None
    peso_nivel1: float
    vizinhos: list[Vizinho]

    def para_dict(self) -> dict:
        return {
            "tema_nivel2": self.tema_nivel2,
            "peso_nivel2": self.peso_nivel2,
            "tema_nivel1": self.tema_nivel1,
            "peso_nivel1": self.peso_nivel1,
            "vizinhos": [asdict(v) for v in self.vizinhos],
        }

    @staticmethod
    def de_dict(dados: dict) -> "VotoVizinhanca":
        return VotoVizinhanca(
            tema_nivel2=None if dados.get("tema_nivel2") is None else int(dados["tema_nivel2"]),
            peso_nivel2=float(dados.get("peso_nivel2", 0.0)),
            tema_nivel1=None if dados.get("tema_nivel1") is None else int(dados["tema_nivel1"]),
            peso_nivel1=float(dados.get("peso_nivel1", 0.0)),
            vizinhos=[Vizinho(str(v["id"]), int(v["tema_id"]), float(v["similaridade"])) for v in dados.get("vizinhos", [])],
        )


VOTO_NULO = VotoVizinhanca(None, 0.0, None, 0.0, [])


def _vencedor(pesos: dict[int, float], total: float) -> tuple[int | None, float]:
    if not pesos or total <= 0:
        return None, 0.0
    tema = max(pesos, key=lambda t: pesos[t])
    return tema, pesos[tema] / total


def votar_vizinhanca(
    texto: str,
    indice_corpus: Indice,
    arvore: ArvoreTemas,
    k: int = K_VIZINHOS,
    excluir: frozenset[str] = frozenset(),
) -> VotoVizinhanca:
    if indice_corpus.tamanho() == 0:
        return VOTO_NULO
    vizinhos = [
        Vizinho(r.id, arvore.canonico(int(r.metadados["tema_id"])), max(r.similaridade, 0.0))
        for r in indice_corpus.buscar(texto, k, excluir)
    ]
    pesos1: dict[int, float] = defaultdict(float)
    pesos2: dict[int, float] = defaultdict(float)
    total = 0.0
    for v in vizinhos:
        if not arvore.publicavel(v.tema_id):
            continue
        total += v.similaridade
        pesos1[arvore.ancestral_nivel1(v.tema_id)] += v.similaridade
        if arvore.nivel(v.tema_id) == 2:
            pesos2[v.tema_id] += v.similaridade
    tema1, peso1 = _vencedor(pesos1, total)
    tema2, peso2 = _vencedor(pesos2, total)
    return VotoVizinhanca(tema2, peso2, tema1, peso1, vizinhos)


def rodar_vizinhanca(
    alvo: str,
    arvore: ArvoreTemas,
    embeddings: Embeddings,
    pasta_saida: Path = CAMINHOS.intermediarios,
    caminho_corpus: Path = CAMINHOS.corpus,
    criar=criar_indice,
) -> Path:
    corpus = carregar_corpus(caminho_corpus) if caminho_corpus.exists() else pd.DataFrame(columns=COLUNAS_CORPUS)
    if len(corpus) == 0:
        registro.warning("corpus ausente ou vazio em %s; votos de vizinhança serão nulos", caminho_corpus)
    indice = montar_indice_corpus(corpus, arvore, embeddings, criar)
    try:
        df = carregar_questoes() if alvo == "questoes" else corpus
        linhas: list[dict] = []
        for id_, texto in zip(df["id"], df["texto"]):
            excluir = frozenset({str(id_)}) if alvo == "corpus" else frozenset()
            voto = votar_vizinhanca(texto, indice, arvore, excluir=excluir)
            linhas.append({"id": str(id_), **voto.para_dict()})
    finally:
        # O Weaviate abre uma conexão por índice; o substituto em memória ignora o fechamento.
        indice.fechar()
    saida = pasta_saida / f"vizinhanca_{alvo}.jsonl"
    escrever_jsonl(saida, linhas)
    registro.info("gravado %s com %d linhas", saida, len(linhas))
    return saida


def main(argumentos: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Voto por vizinhança sobre o corpus de referência.")
    parser.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")
    args = parser.parse_args(argumentos)
    rodar_vizinhanca(args.alvo, ArvoreTemas.carregar(), criar_embeddings())


if __name__ == "__main__":
    main()
