"""CLI `classificar`: encadeia as etapas e gera publicacao.csv e previsao.txt."""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Callable

from classificador import ancora, calibracao, candidatos, decisao, llm, saida, vizinhanca
from classificador.arvore import ArvoreTemas
from classificador.config import CAMINHOS
from classificador.dados import carregar_questoes, ler_jsonl
from classificador.embeddings import criar_embeddings

registro = logging.getLogger(__name__)


def caminho_corpus() -> Path:
    return CAMINHOS.corpus


def etapa_candidatos(passada: int, alvo: str = "questoes") -> None:
    candidatos.rodar_candidatos(alvo, passada, ArvoreTemas.carregar(), criar_embeddings())


def etapa_ancora() -> None:
    ancora.rodar_ancora()


def etapa_votos(alvo: str, limite: int | None = None) -> None:
    caminho = CAMINHOS.intermediarios / f"candidatos_{alvo}_p2.jsonl"
    llm.rodar_votos(alvo, ArvoreTemas.carregar(), caminho, llm.criar_classificadores(), limite=limite)


def etapa_vizinhanca(alvo: str) -> None:
    vizinhanca.rodar_vizinhanca(alvo, ArvoreTemas.carregar(), criar_embeddings())


def etapa_calibrar() -> None:
    calibracao.rodar_calibracao(ArvoreTemas.carregar())


def etapa_decidir(alvo: str = "questoes") -> None:
    decisao.rodar_decisoes(alvo, ArvoreTemas.carregar(), decisao.carregar_limiares())


def etapa_publicar() -> None:
    arvore = ArvoreTemas.carregar()
    decisoes = ler_jsonl(CAMINHOS.intermediarios / "decisoes_questoes.jsonl")
    ids = [str(i) for i in carregar_questoes()["id"]]
    saida.escrever_publicacao(decisoes, ids, arvore)
    resumo = json.loads((CAMINHOS.intermediarios / "calibracao_resumo.json").read_text(encoding="utf-8"))
    calibracao.escrever_previsao(
        CAMINHOS.previsao,
        resumo["precisao_prevista"],
        tuple(resumo["precisao_intervalo"]),
        resumo["cobertura"],
        tuple(resumo["cobertura_intervalo"]),
        calibracao.montar_texto_previsao(resumo),
    )
    contagem = Counter(d["decisao"] for d in decisoes)
    print(f"publicacao.csv: {dict(contagem)}")
    print(f"previsao.txt: precisão {resumo['precisao_prevista']:.2f} {resumo['precisao_intervalo']}, cobertura {resumo['cobertura']:.2f}")


ETAPAS_TUDO: list[tuple[str, Callable[[], None]]] = [
    ("candidatos p1 questoes", lambda: etapa_candidatos(1, "questoes")),
    ("ancora", etapa_ancora),
    ("candidatos p2 questoes", lambda: etapa_candidatos(2, "questoes")),
    ("candidatos p2 corpus", lambda: etapa_candidatos(2, "corpus")),
    ("votos questoes", lambda: etapa_votos("questoes")),
    ("votos corpus", lambda: etapa_votos("corpus")),
    ("vizinhanca questoes", lambda: etapa_vizinhanca("questoes")),
    ("vizinhanca corpus", lambda: etapa_vizinhanca("corpus")),
    ("calibrar", etapa_calibrar),
    ("decidir", lambda: etapa_decidir("questoes")),
    ("publicar", etapa_publicar),
]


def rodar_tudo(etapas: list[tuple[str, Callable[[], None]]] = ETAPAS_TUDO) -> None:
    corpus = caminho_corpus()
    if not corpus.exists():
        raise FileNotFoundError(
            f"corpus de referência ausente em {corpus}. O pipeline completo precisa dele para calibrar. "
            "Use o corpus commitado ou rode as etapas individualmente."
        )
    for nome, funcao in etapas:
        registro.info("=== etapa: %s ===", nome)
        funcao()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="classificar", description="Classificação de questões em temas (case Vício).")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("candidatos", help="temas candidatos por questão")
    p.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")
    p.add_argument("--passada", type=int, choices=[1, 2], default=1)

    sub.add_parser("ancora", help="gera a planilha da âncora manual")

    p = sub.add_parser("votos", help="votos dos dois modelos de linguagem")
    p.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")
    p.add_argument("--limite", type=int, default=None)

    p = sub.add_parser("vizinhanca", help="voto por vizinhança sobre o corpus")
    p.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")

    sub.add_parser("calibrar", help="calibra limiares no corpus e prepara a previsão")

    p = sub.add_parser("decidir", help="aplica as regras de decisão")
    p.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")

    sub.add_parser("publicar", help="grava publicacao.csv e previsao.txt")
    sub.add_parser("tudo", help="roda todas as etapas na ordem")

    args = parser.parse_args(argv)
    if args.comando == "candidatos":
        etapa_candidatos(args.passada, args.alvo)
    elif args.comando == "ancora":
        etapa_ancora()
    elif args.comando == "votos":
        etapa_votos(args.alvo, args.limite)
    elif args.comando == "vizinhanca":
        etapa_vizinhanca(args.alvo)
    elif args.comando == "calibrar":
        etapa_calibrar()
    elif args.comando == "decidir":
        etapa_decidir(args.alvo)
    elif args.comando == "publicar":
        etapa_publicar()
    elif args.comando == "tudo":
        rodar_tudo()


if __name__ == "__main__":
    main()
