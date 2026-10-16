"""Planilha da âncora manual: 40 questões sorteadas, com candidatos, para rotular às cegas."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

import pandas as pd

from classificador.arvore import ArvoreTemas
from classificador.config import CAMINHOS, SEMENTE
from classificador.dados import carregar_questoes, ler_jsonl

registro = logging.getLogger(__name__)

N_ANCORA = 40
COLUNAS = ["id", "disciplina_origem", "texto", "candidatos", "tema_id_gilson", "observacao"]
COLUNAS_ROTULO = ["tema_id_gilson", "observacao"]
# A tela de revisão grava tema_id 0 quando o professor decide que nenhum tema da árvore serve.
TEMA_FORA = 0


def ler_csv_planilha(caminho: Path, **opcoes) -> pd.DataFrame:
    """Lê CSV gravado por nós ou salvo pelo Excel: separador detectado (vírgula ou ponto e vírgula) e BOM ignorado."""
    return pd.read_csv(caminho, sep=None, engine="python", encoding="utf-8-sig", **opcoes)


def planilha_tem_rotulos(caminho: Path) -> bool:
    """Verdadeiro se alguma célula de rótulo ou observação está preenchida, ou se não dá para ler o arquivo."""
    try:
        planilha = ler_csv_planilha(caminho, dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError, csv.Error) as erro:
        registro.warning("não consegui ler %s (%s); trato como planilha rotulada", caminho, erro)
        return True
    return any(planilha[c].str.strip().ne("").any() for c in COLUNAS_ROTULO if c in planilha.columns)


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
        "observacao": "",
    })
    return planilha[COLUNAS].reset_index(drop=True)


def rodar_ancora(
    caminho_candidatos: Path = CAMINHOS.intermediarios / "candidatos_questoes_p1.jsonl",
    saida: Path = CAMINHOS.ancora_planilha,
) -> Path:
    if saida.exists() and planilha_tem_rotulos(saida):
        raise FileExistsError(
            f"{saida} já tem rótulos ou observações preenchidos; mova o arquivo para outro lugar antes de gerar "
            "a planilha de novo, para não perder a rotulagem."
        )
    arvore = ArvoreTemas.carregar()
    questoes = carregar_questoes()
    candidatos = {linha["id"]: linha["candidatos"] for linha in ler_jsonl(caminho_candidatos)}
    planilha = gerar_planilha_ancora(questoes, candidatos, arvore)
    saida.parent.mkdir(parents=True, exist_ok=True)
    # Com BOM, o Excel abre a planilha com os acentos certos.
    planilha.to_csv(saida, index=False, encoding="utf-8-sig")
    registro.info("planilha da âncora com %d questões em %s", len(planilha), saida)
    return saida


def carregar_ancora_manual(arvore: ArvoreTemas, caminho: Path = CAMINHOS.ancora_manual) -> pd.DataFrame:
    """Lê o gabarito da âncora exportado pela tela de revisão (id, tema_id, observacao).

    tema_id 0 (TEMA_FORA) vem da tela e significa "nenhum tema serve": a questão fica fora da árvore e a linha
    é mantida. Qualquer outro valor precisa ser um tema publicável.
    """
    df = ler_csv_planilha(caminho, dtype={"id": str})
    if "tema_id" not in df.columns:
        raise ValueError(f"âncora em {caminho} sem a coluna tema_id; colunas encontradas: {list(df.columns)}")
    em_branco = df["tema_id"].isna() | (df["tema_id"].astype(str).str.strip() == "")
    if em_branco.any():
        raise ValueError(f"âncora em {caminho} com tema_id em branco nas questões: {list(df.loc[em_branco, 'id'])}")
    df["tema_id"] = df["tema_id"].astype(int)
    invalidos = [int(t) for t in df["tema_id"] if int(t) != TEMA_FORA and not arvore.publicavel(int(t))]
    if invalidos:
        raise ValueError(f"âncora com tema(s) não publicável(is): {invalidos}")
    return df[["id", "tema_id"]].reset_index(drop=True)
