"""Temas candidatos por questão: similaridade com temas, vizinhos do corpus e pais."""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from langchain_core.embeddings import Embeddings

from classificador.arvore import ArvoreTemas
from classificador.config import CAMINHOS
from classificador.dados import carregar_corpus, carregar_questoes, escrever_jsonl
from classificador.embeddings import criar_embeddings
from classificador.indice import Indice, criar_indice

registro = logging.getLogger(__name__)

K_TEMAS = 8
K_CORPUS = 10
TETO = 12


@dataclass(frozen=True)
class Candidato:
    tema_id: int
    origem: str
    similaridade: float


def montar_indice_temas(arvore: ArvoreTemas, embeddings: Embeddings, criar=criar_indice) -> Indice:
    ids = arvore.candidatos_possiveis()
    indice = criar("Tema", embeddings)
    try:
        indice.adicionar([str(t) for t in ids], [arvore.documento(t) for t in ids], [{"tema_id": t} for t in ids])
    except Exception:
        # O índice ainda não foi devolvido, então quem chamou não tem como fechá-lo.
        indice.fechar()
        raise
    return indice


def montar_indice_corpus(corpus: pd.DataFrame, arvore: ArvoreTemas, embeddings: Embeddings, criar=criar_indice) -> Indice:
    indice = criar("CorpusQuestao", embeddings)
    if len(corpus) == 0:
        return indice
    ids = [str(i) for i in corpus["id"]]
    metadados = [{"tema_id": arvore.canonico(int(t)), "id": str(i)} for t, i in zip(corpus["tema_id"], corpus["id"])]
    try:
        indice.adicionar(ids, list(corpus["texto"]), metadados)
    except Exception:
        indice.fechar()
        raise
    return indice


def _registrar(acumulado: dict[int, Candidato], tema_id: int, origem: str, similaridade: float) -> None:
    atual = acumulado.get(tema_id)
    if atual is None:
        acumulado[tema_id] = Candidato(tema_id, origem, similaridade)
    elif similaridade > atual.similaridade:
        acumulado[tema_id] = Candidato(tema_id, atual.origem, similaridade)


def buscar_candidatos(
    texto: str,
    indice_temas: Indice,
    arvore: ArvoreTemas,
    indice_corpus: Indice | None = None,
    excluir_corpus: frozenset[str] = frozenset(),
    k_temas: int = K_TEMAS,
    k_corpus: int = K_CORPUS,
    teto: int = TETO,
) -> list[Candidato]:
    acumulado: dict[int, Candidato] = {}
    for resultado in indice_temas.buscar(texto, k_temas):
        _registrar(acumulado, int(resultado.metadados["tema_id"]), "tema", resultado.similaridade)
    if indice_corpus is not None and indice_corpus.tamanho() > 0:
        for resultado in indice_corpus.buscar(texto, k_corpus, excluir=excluir_corpus):
            tema_id = arvore.canonico(int(resultado.metadados["tema_id"]))
            if arvore.publicavel(tema_id):
                _registrar(acumulado, tema_id, "corpus", resultado.similaridade)
    for candidato in list(acumulado.values()):
        if arvore.nivel(candidato.tema_id) == 2:
            pai = arvore.pai(candidato.tema_id)
            if pai is not None and arvore.publicavel(pai):
                _registrar(acumulado, pai, "pai", candidato.similaridade)
    ordenados = sorted(acumulado.values(), key=lambda c: (-c.similaridade, arvore.nivel(c.tema_id)))
    return ordenados[:teto]


def candidatos_para_dict(lista: list[Candidato]) -> list[dict]:
    return [asdict(c) for c in lista]


def candidatos_de_dict(lista: list[dict]) -> list[Candidato]:
    return [Candidato(int(c["tema_id"]), str(c["origem"]), float(c["similaridade"])) for c in lista]


def rodar_candidatos(
    alvo: str,
    passada: int,
    arvore: ArvoreTemas,
    embeddings: Embeddings,
    pasta_saida: Path = CAMINHOS.intermediarios,
    criar=criar_indice,
) -> Path:
    if alvo not in {"questoes", "corpus"}:
        raise ValueError("alvo deve ser 'questoes' ou 'corpus'")
    if alvo == "corpus" and passada != 2:
        raise ValueError("o corpus só roda na passada 2")
    indice_temas: Indice | None = None
    indice_corpus: Indice | None = None
    try:
        indice_temas = montar_indice_temas(arvore, embeddings, criar)
        if passada == 2:
            if CAMINHOS.corpus.exists():
                corpus = carregar_corpus()
            else:
                registro.warning("corpus ausente em %s; passada 2 roda só com os temas", CAMINHOS.corpus)
                corpus = pd.DataFrame(columns=["id", "tema_id", "texto"])
            indice_corpus = montar_indice_corpus(corpus, arvore, embeddings, criar)
        if alvo == "corpus" and not CAMINHOS.corpus.exists():
            raise FileNotFoundError(f"corpus ausente em {CAMINHOS.corpus}")
        df = carregar_questoes() if alvo == "questoes" else carregar_corpus()
        linhas: list[dict] = []
        for id_, texto in zip(df["id"], df["texto"]):
            excluir = frozenset({str(id_)}) if alvo == "corpus" else frozenset()
            lista = buscar_candidatos(texto, indice_temas, arvore, indice_corpus, excluir_corpus=excluir)
            linhas.append({"id": str(id_), "candidatos": candidatos_para_dict(lista)})
    finally:
        # O Weaviate abre uma conexão por índice; o substituto em memória ignora o fechamento.
        if indice_corpus is not None:
            indice_corpus.fechar()
        if indice_temas is not None:
            indice_temas.fechar()
    saida = pasta_saida / f"candidatos_{alvo}_p{passada}.jsonl"
    escrever_jsonl(saida, linhas)
    registro.info("gravado %s com %d linhas", saida, len(linhas))
    if alvo == "questoes" and passada == 1:
        alvo_corpus: set[int] = set()
        for linha in linhas:
            for c in linha["candidatos"]:
                alvo_corpus.add(int(c["tema_id"]))
                if arvore.nivel(int(c["tema_id"])) == 2:
                    pai = arvore.pai(int(c["tema_id"]))
                    if pai is not None and arvore.publicavel(pai):
                        alvo_corpus.add(pai)
        caminho_alvo = pasta_saida / "temas_alvo_corpus.json"
        caminho_alvo.write_text(json.dumps(sorted(alvo_corpus)), encoding="utf-8")
        registro.info("%d temas alvo para o corpus em %s", len(alvo_corpus), caminho_alvo)
    return saida


def main(argumentos: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Gera os temas candidatos por questão.")
    parser.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")
    parser.add_argument("--passada", type=int, choices=[1, 2], default=1)
    args = parser.parse_args(argumentos)
    rodar_candidatos(args.alvo, args.passada, ArvoreTemas.carregar(), criar_embeddings())


if __name__ == "__main__":
    main()
