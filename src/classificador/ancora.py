"""Planilha da âncora manual: 40 questões sorteadas, com candidatos, para rotular às cegas."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from classificador.arvore import ArvoreTemas
from classificador.config import CAMINHOS, SEMENTE
from classificador.dados import carregar_questoes, ler_jsonl

registro = logging.getLogger(__name__)

N_ANCORA = 40
COLUNAS = ["id", "disciplina_origem", "texto", "candidatos", "tema_id_gilson", "tema_id_segunda_passagem", "observacao"]


def sortear_ancora(questoes: pd.DataFrame, n: int = N_ANCORA, semente: int = SEMENTE) -> pd.DataFrame:
    tamanhos = questoes.groupby("disciplina_origem").size()
    cotas = (tamanhos / len(questoes) * n).round().astype(int)
    cotas[tamanhos.idxmax()] += n - int(cotas.sum())
    partes = []
    for disciplina, cota in cotas.items():
        grupo = questoes[questoes["disciplina_origem"] == disciplina]
        if cota > 0:
            partes.append(grupo.sample(n=min(int(cota), len(grupo)), random_state=semente))
    return pd.concat(partes).sort_values("id").reset_index(drop=True)


def formatar_candidatos_para_planilha(candidatos: list[dict], arvore: ArvoreTemas) -> str:
    linhas = []
    for c in candidatos:
        tema_id = int(c["tema_id"])
        documento = arvore.documento(tema_id).split("\n", 1)
        descricao = documento[1][:200] if len(documento) > 1 else ""
        linhas.append(f"{tema_id} | {arvore.caminho(tema_id)} | {descricao}")
    return "\n".join(linhas)


def gerar_planilha_ancora(
    questoes: pd.DataFrame,
    candidatos_por_id: dict[str, list[dict]],
    arvore: ArvoreTemas,
    n: int = N_ANCORA,
    semente: int = SEMENTE,
) -> pd.DataFrame:
    amostra = sortear_ancora(questoes, n, semente)
    planilha = pd.DataFrame({
        "id": amostra["id"],
        "disciplina_origem": amostra["disciplina_origem"],
        "texto": amostra["texto"],
        "candidatos": [formatar_candidatos_para_planilha(candidatos_por_id[i], arvore) for i in amostra["id"]],
        "tema_id_gilson": "",
        "tema_id_segunda_passagem": "",
        "observacao": "",
    })
    return planilha[COLUNAS].reset_index(drop=True)


def rodar_ancora(
    caminho_candidatos: Path = CAMINHOS.intermediarios / "candidatos_questoes_p1.jsonl",
    saida: Path = CAMINHOS.ancora_planilha,
) -> Path:
    arvore = ArvoreTemas.carregar()
    questoes = carregar_questoes()
    candidatos = {linha["id"]: linha["candidatos"] for linha in ler_jsonl(caminho_candidatos)}
    planilha = gerar_planilha_ancora(questoes, candidatos, arvore)
    saida.parent.mkdir(parents=True, exist_ok=True)
    planilha.to_csv(saida, index=False, encoding="utf-8")
    registro.info("planilha da âncora com %d questões em %s", len(planilha), saida)
    return saida


def carregar_ancora_manual(arvore: ArvoreTemas, caminho: Path = CAMINHOS.ancora_manual) -> pd.DataFrame:
    df = pd.read_csv(caminho, dtype={"id": str})
    df["tema_id"] = df["tema_id"].astype(int)
    invalidos = [int(t) for t in df["tema_id"] if not arvore.publicavel(int(t))]
    if invalidos:
        raise ValueError(f"âncora com tema(s) não publicável(is): {invalidos}")
    return df[["id", "tema_id"]].reset_index(drop=True)
