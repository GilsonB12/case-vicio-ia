"""Escrita e validação do publicacao.csv no formato do LEIA-ME."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from classificador.arvore import ArvoreTemas
from classificador.config import CAMINHOS

COLUNAS = ["id", "decisao", "tema_central_id", "extras_ids", "confianca", "motivo"]
DECISOES = {"publicar", "revisar", "fora"}


def montar_publicacao(decisoes: list[dict]) -> pd.DataFrame:
    linhas = []
    for d in decisoes:
        central = d.get("tema_central_id")
        confianca = d.get("confianca")
        linhas.append({
            "id": str(d["id"]),
            "decisao": str(d["decisao"]),
            "tema_central_id": "" if central is None else str(int(central)),
            "extras_ids": ";".join(str(int(e)) for e in d.get("extras_ids") or []),
            "confianca": "" if confianca is None else f"{float(confianca):.2f}",
            "motivo": str(d.get("motivo") or ""),
        })
    return pd.DataFrame(linhas, columns=COLUNAS)


def _inteiro(valor: str) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def validar_publicacao(df: pd.DataFrame, ids_esperados: list[str], arvore: ArvoreTemas) -> list[str]:
    erros: list[str] = []
    if list(df.columns) != COLUNAS:
        erros.append(f"colunas devem ser {COLUNAS}, vieram {list(df.columns)}")
        return erros
    repetidos = df["id"][df["id"].duplicated()].tolist()
    if repetidos:
        erros.append(f"ids repetidos: {sorted(set(repetidos))}")
    faltando = sorted(set(ids_esperados) - set(df["id"]))
    sobrando = sorted(set(df["id"]) - set(ids_esperados))
    if faltando:
        erros.append(f"ids faltando: {faltando[:10]}")
    if sobrando:
        erros.append(f"ids inesperados: {sobrando[:10]}")
    for _, linha in df.iterrows():
        id_ = linha["id"]
        decisao = linha["decisao"]
        if decisao not in DECISOES:
            erros.append(f"{id_}: decisao inválida '{decisao}'")
            continue
        central = _inteiro(linha["tema_central_id"]) if linha["tema_central_id"] != "" else None
        if decisao in {"publicar", "revisar"}:
            if central is None:
                erros.append(f"{id_}: tema_central_id obrigatório em {decisao}")
            elif not arvore.publicavel(central):
                erros.append(f"{id_}: tema_central_id {central} não é publicável")
        elif linha["tema_central_id"] != "":
            erros.append(f"{id_}: tema_central_id deve ficar vazio em fora")
        if decisao in {"revisar", "fora"} and not linha["motivo"].strip():
            erros.append(f"{id_}: motivo obrigatório em {decisao}")
        if linha["confianca"] != "":
            try:
                valor = float(linha["confianca"])
                if not 0.0 <= valor <= 1.0:
                    raise ValueError
            except ValueError:
                erros.append(f"{id_}: confianca '{linha['confianca']}' fora de [0, 1]")
        extras = [e for e in linha["extras_ids"].split(";") if e != ""]
        if len(extras) != len(set(extras)):
            erros.append(f"{id_}: extras_ids repetidos")
        for extra in extras:
            tema = _inteiro(extra)
            if tema is None or not arvore.publicavel(tema):
                erros.append(f"{id_}: extras_ids contém {extra}, que não é publicável")
            elif tema == central:
                erros.append(f"{id_}: extras_ids contém o próprio tema central {tema}")
    return erros


def escrever_publicacao(
    decisoes: list[dict],
    ids_esperados: list[str],
    arvore: ArvoreTemas,
    caminho: Path = CAMINHOS.publicacao,
) -> Path:
    df = montar_publicacao(decisoes)
    erros = validar_publicacao(df, ids_esperados, arvore)
    if erros:
        raise ValueError("publicacao.csv inválido:\n" + "\n".join(erros))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(caminho, index=False, encoding="utf-8", lineterminator="\n")
    return caminho


def ler_publicacao(caminho: Path = CAMINHOS.publicacao) -> pd.DataFrame:
    return pd.read_csv(caminho, dtype=str, keep_default_na=False)
