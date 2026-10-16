"""CLI `classificar`: encadeia as etapas e gera publicacao.csv e previsao.txt."""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Callable

from classificador import ancora, calibracao, candidatos, decisao, llm, reparo, saida, vizinhanca
from classificador.arvore import ArvoreTemas
from classificador.config import CAMINHOS
from classificador.dados import carregar_questoes, ler_jsonl
from classificador.embeddings import criar_embeddings

registro = logging.getLogger(__name__)

# Lido pelas etapas de ETAPAS_TUDO na hora da chamada; rodar_tudo troca durante a execução e restaura no fim.
# Fora do `tudo`, as etapas sempre recalculam.
_recalcular_no_tudo = True


def caminho_corpus() -> Path:
    return CAMINHOS.corpus


def _reaproveitar(saida: Path, recalcular: bool) -> bool:
    if not recalcular and saida.exists():
        registro.info("reaproveitando %s", saida)
        return True
    return False


def etapa_candidatos(passada: int, alvo: str = "questoes", recalcular: bool = True) -> None:
    if _reaproveitar(CAMINHOS.intermediarios / f"candidatos_{alvo}_p{passada}.jsonl", recalcular):
        return
    candidatos.rodar_candidatos(alvo, passada, ArvoreTemas.carregar(), criar_embeddings())


def etapa_ancora(pular_se_existir: bool = True) -> None:
    planilha = CAMINHOS.ancora_planilha
    if pular_se_existir and planilha.exists():
        registro.info("planilha da âncora já existe em %s; etapa pulada para não sobrescrever rótulos", planilha)
        return
    ancora.rodar_ancora(saida=planilha)


def etapa_votos(alvo: str, limite: int | None = None) -> None:
    caminho = CAMINHOS.intermediarios / f"candidatos_{alvo}_p2.jsonl"
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho} não existe; rode `classificar candidatos --alvo {alvo} --passada 2` antes dos votos"
        )
    llm.rodar_votos(alvo, ArvoreTemas.carregar(), caminho, llm.criar_classificadores(), limite=limite)


def etapa_reparar(alvo: str, recalcular: bool = False) -> None:
    reparo.rodar_reparo(alvo, ArvoreTemas.carregar(), criar_embeddings(), llm.criar_classificadores(),
                        pasta=CAMINHOS.intermediarios, recalcular=recalcular)


def etapa_vizinhanca(alvo: str, recalcular: bool = True) -> None:
    if _reaproveitar(CAMINHOS.intermediarios / f"vizinhanca_{alvo}.jsonl", recalcular):
        return
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
    inferior, superior = resumo["precisao_intervalo"]
    print(f"publicacao.csv: {dict(contagem)}")
    print(f"previsao.txt: precisão {resumo['precisao_prevista']:.2f} [{inferior:.2f}, {superior:.2f}], cobertura {resumo['cobertura']:.2f}")


ETAPAS_TUDO: list[tuple[str, Callable[[], None]]] = [
    ("candidatos p1 questoes", lambda: etapa_candidatos(1, "questoes", recalcular=_recalcular_no_tudo)),
    ("ancora", etapa_ancora),
    ("candidatos p2 questoes", lambda: etapa_candidatos(2, "questoes", recalcular=_recalcular_no_tudo)),
    ("candidatos p2 corpus", lambda: etapa_candidatos(2, "corpus", recalcular=_recalcular_no_tudo)),
    ("votos questoes", lambda: etapa_votos("questoes")),
    ("reparo questoes", lambda: etapa_reparar("questoes", recalcular=_recalcular_no_tudo)),
    ("votos corpus", lambda: etapa_votos("corpus")),
    ("reparo corpus", lambda: etapa_reparar("corpus", recalcular=_recalcular_no_tudo)),
    ("vizinhanca questoes", lambda: etapa_vizinhanca("questoes", recalcular=_recalcular_no_tudo)),
    ("vizinhanca corpus", lambda: etapa_vizinhanca("corpus", recalcular=_recalcular_no_tudo)),
    ("calibrar", etapa_calibrar),
    ("decidir", lambda: etapa_decidir("questoes")),
    ("publicar", etapa_publicar),
]


def rodar_tudo(etapas: list[tuple[str, Callable[[], None]]] = ETAPAS_TUDO, recalcular: bool = False) -> None:
    """Roda as etapas na ordem. Sem recalcular, candidatos e vizinhança com arquivo pronto são reaproveitados;
    os votos e o reparo vêm do cache e a planilha da âncora existente nunca é regravada."""
    global _recalcular_no_tudo
    corpus = caminho_corpus()
    if not corpus.exists():
        raise FileNotFoundError(
            f"corpus de referência ausente em {corpus}. O pipeline completo precisa dele para calibrar. "
            "Use o corpus commitado ou rode as etapas individualmente."
        )
    _recalcular_no_tudo = recalcular
    try:
        for nome, funcao in etapas:
            registro.info("=== etapa: %s ===", nome)
            funcao()
    finally:
        _recalcular_no_tudo = True


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
    p.add_argument("--verificar", action="store_true", help="só testa chave e modelo de cada provedor")

    p = sub.add_parser("reparar", help="amplia os candidatos pela justificativa do voto nulo e revota")
    p.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")
    p.add_argument("--recalcular", action="store_true",
                   help="refaz também as questões já reparadas, a partir dos votos originais")

    p = sub.add_parser("vizinhanca", help="voto por vizinhança sobre o corpus")
    p.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")

    sub.add_parser("calibrar", help="calibra limiares no corpus e prepara a previsão")

    p = sub.add_parser("decidir", help="aplica as regras de decisão")
    p.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")

    sub.add_parser("publicar", help="grava publicacao.csv e previsao.txt")
    p = sub.add_parser("tudo", help="roda todas as etapas na ordem, reaproveitando os intermediários prontos")
    p.add_argument("--recalcular", action="store_true", help="recalcula candidatos e vizinhança mesmo com arquivo pronto")

    args = parser.parse_args(argv)
    if args.comando == "candidatos":
        etapa_candidatos(args.passada, args.alvo)
    elif args.comando == "ancora":
        etapa_ancora(pular_se_existir=False)
    elif args.comando == "votos":
        if args.verificar:
            for provedor, estado in llm.verificar_provedores().items():
                print(f"{provedor}: {estado}")
        else:
            etapa_votos(args.alvo, args.limite)
    elif args.comando == "reparar":
        etapa_reparar(args.alvo, recalcular=args.recalcular)
    elif args.comando == "vizinhanca":
        etapa_vizinhanca(args.alvo)
    elif args.comando == "calibrar":
        etapa_calibrar()
    elif args.comando == "decidir":
        etapa_decidir(args.alvo)
    elif args.comando == "publicar":
        etapa_publicar()
    elif args.comando == "tudo":
        rodar_tudo(recalcular=args.recalcular)


if __name__ == "__main__":
    main()
