"""Consolida os lotes coletados em data/coleta no corpus de referência.

Segue a seção "Pós-processamento" de docs/projeto/coleta-corpus.md. As regras rodam nesta ordem,
e cada questão descartada fica registrada com o motivo:

1. `schema`: falta campo, tipo errado, alternativas vazias ou confiança fora de alta/media/baixa.
2. `tema_nao_publicavel`: o tema, depois de canonicalizado, não é publicável na árvore.
3. `enunciado_curto`: enunciado sem HTML com menos de 40 caracteres.
4. `duplicata_texto`: mesmo enunciado e alternativas, sem caixa, acento nem espaços extras.
5. `igual_a_questao_do_case` e `duplicata_embedding`: similaridade de cosseno de pelo menos 0,95
   com uma das 359 questões do case ou com uma questão do corpus já mantida.

Uso: uv run python scripts/consolidar_corpus.py [--pasta data/coleta] [--saida data/corpus_referencia.jsonl]
     [--resumo data/intermediarios/corpus_consolidacao.json] [--sem-embeddings]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from langchain_core.embeddings import Embeddings

from classificador.arvore import ArvoreTemas
from classificador.config import CAMINHOS, RAIZ, ChaveAusenteError
from classificador.dados import carregar_questoes, escrever_jsonl, limpar_html, montar_texto
from classificador.embeddings import criar_embeddings

PASTA_COLETA = RAIZ / "data" / "coleta"
RESUMO = CAMINHOS.intermediarios / "corpus_consolidacao.json"
PADRAO_LOTE = "lote-*.jsonl"

LIMIAR_SIMILARIDADE = 0.95
MINIMO_ENUNCIADO = 40
TAMANHO_TRECHO = 60
CONFIANCAS = ("alta", "media", "baixa")
MOTIVOS = (
    "schema",
    "tema_nao_publicavel",
    "enunciado_curto",
    "duplicata_texto",
    "igual_a_questao_do_case",
    "duplicata_embedding",
)
CAMPOS: dict[str, type] = {
    "tema_id": int,
    "enunciado": str,
    "comando": str,
    "alternativas": dict,
    "url": str,
    "site": str,
    "banca_ano": str,
    "confianca_fonte": str,
    "gabarito": str,
}

_ESPACOS = re.compile(r"\s+")


class SemLotesError(FileNotFoundError):
    """Nenhum arquivo lote-*.jsonl na pasta de coleta."""


@dataclass
class Item:
    lote: str
    linha: int
    dados: dict
    texto: str = ""

    @property
    def posicao(self) -> str:
        return f"{self.lote}:{self.linha}"


def nome_do_lote(caminho: Path) -> str:
    """`lote-01.jsonl` vira `01`; `lote-piloto.jsonl` vira `piloto`."""
    return caminho.stem.removeprefix("lote-")


def arquivos_de_lote(pasta: Path) -> list[Path]:
    return sorted(Path(pasta).glob(PADRAO_LOTE), key=nome_do_lote)


def normalizar_texto(texto: str) -> str:
    """Minúsculo, sem acento e com espaços colapsados."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return _ESPACOS.sub(" ", sem_acento.lower()).strip()


def chave_de_texto(dados: dict) -> str:
    """Enunciado e alternativas sem HTML, normalizados: duas questões com a mesma chave são a mesma."""
    partes = [limpar_html(dados["enunciado"])]
    partes.extend(f"{letra} {limpar_html(texto)}" for letra, texto in dados["alternativas"].items())
    return normalizar_texto(" ".join(partes))


def problema_de_esquema(objeto: object) -> str | None:
    """Descreve o primeiro defeito de formato da linha, ou None se ela está no formato do protocolo."""
    if not isinstance(objeto, dict):
        return "a linha não é um objeto JSON"
    for campo, tipo in CAMPOS.items():
        if campo not in objeto:
            return f"campo ausente: {campo}"
        valor = objeto[campo]
        tipo_certo = isinstance(valor, tipo) and not (tipo is int and isinstance(valor, bool))
        if not tipo_certo:
            return f"tipo errado em {campo}: {type(valor).__name__}"
    alternativas = objeto["alternativas"]
    if not alternativas:
        return "alternativas vazias"
    if not all(isinstance(letra, str) and isinstance(texto, str) for letra, texto in alternativas.items()):
        return "alternativas devem mapear letra em texto"
    if objeto["confianca_fonte"] not in CONFIANCAS:
        return f"confianca_fonte inválida: {objeto['confianca_fonte']!r}"
    return None


def _ler_linhas(caminho: Path) -> list[tuple[int, str | None, str]]:
    """(número da linha, texto ou None se não é UTF-8, texto para o trecho), sem as linhas em branco."""
    linhas: list[tuple[int, str | None, str]] = []
    for numero, bruta in enumerate(caminho.read_bytes().split(b"\n"), start=1):
        bruta = bruta.rstrip(b"\r")
        if numero == 1:
            bruta = bruta.removeprefix(b"\xef\xbb\xbf")
        try:
            texto: str | None = bruta.decode("utf-8")
        except UnicodeDecodeError:
            texto = None
        legivel = bruta.decode("utf-8", errors="replace")
        if not legivel.strip():
            continue
        linhas.append((numero, texto, legivel))
    return linhas


def _trecho(objeto: object, bruta: str) -> str:
    if isinstance(objeto, dict) and isinstance(objeto.get("enunciado"), str):
        return limpar_html(objeto["enunciado"])[:TAMANHO_TRECHO]
    return bruta.strip()[:TAMANHO_TRECHO]


def _matriz_normalizada(vetores: list[list[float]]) -> np.ndarray:
    matriz = np.asarray(vetores, dtype=np.float32)
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return matriz / normas


class _Consolidacao:
    def __init__(self, arvore: ArvoreTemas) -> None:
        self.arvore = arvore
        self.descartadas: list[dict] = []
        self.lidas: Counter[str] = Counter()
        self.motivos_por_lote: dict[str, Counter[str]] = {}
        self.canonicalizados: list[dict] = []

    def descartar(self, lote: str, linha: int, motivo: str, trecho: str, detalhe: str = "", referencia: str | None = None) -> None:
        self.motivos_por_lote.setdefault(lote, Counter())[motivo] += 1
        self.descartadas.append({
            "lote": lote, "linha": linha, "motivo": motivo, "detalhe": detalhe,
            "referencia": referencia, "trecho": trecho,
        })

    def ler_lote(self, caminho: Path, chaves_vistas: dict[str, str]) -> list[Item]:
        """Regras 1 a 4, na ordem das linhas do arquivo."""
        lote = nome_do_lote(caminho)
        self.motivos_por_lote.setdefault(lote, Counter())
        mantidos: list[Item] = []
        for numero, texto, legivel in _ler_linhas(caminho):
            self.lidas[lote] += 1
            if texto is None:
                self.descartar(lote, numero, "schema", _trecho(None, legivel), "a linha não é UTF-8 válido")
                continue
            try:
                objeto = json.loads(texto)
            except ValueError as erro:
                self.descartar(lote, numero, "schema", _trecho(None, legivel), f"JSON inválido: {erro}")
                continue
            problema = problema_de_esquema(objeto)
            if problema:
                self.descartar(lote, numero, "schema", _trecho(objeto, legivel), problema)
                continue
            trecho = _trecho(objeto, legivel)

            original = objeto["tema_id"]
            canonico = self.arvore.canonico(original)
            if not self.arvore.publicavel(canonico):
                self.descartar(lote, numero, "tema_nao_publicavel", trecho, f"tema {original}")
                continue
            if canonico != original:
                self.canonicalizados.append({"lote": lote, "linha": numero, "de": original, "para": canonico})

            tamanho = len(limpar_html(objeto["enunciado"]))
            if tamanho < MINIMO_ENUNCIADO:
                self.descartar(lote, numero, "enunciado_curto", trecho, f"{tamanho} caracteres sem HTML")
                continue

            chave = chave_de_texto(objeto)
            if chave in chaves_vistas:
                self.descartar(lote, numero, "duplicata_texto", trecho, referencia=chaves_vistas[chave])
                continue

            dados = {campo: objeto[campo] for campo in CAMPOS}
            dados["tema_id"] = canonico
            item = Item(lote, numero, dados, montar_texto(dados["enunciado"], dados["comando"], dados["alternativas"]))
            chaves_vistas[chave] = item.posicao
            mantidos.append(item)
        return mantidos

    def filtrar_por_embedding(self, itens: list[Item], embeddings: Embeddings, questoes_case: pd.DataFrame) -> list[Item]:
        """Regra 5: um produto de matrizes contra as 359 e uma comparação com cada questão já mantida."""
        if not itens:
            return itens
        textos_case = [str(t) for t in questoes_case["texto"]]
        ids_case = [str(i) for i in questoes_case["id"]]
        case = _matriz_normalizada(embeddings.embed_documents(textos_case))
        corpus = _matriz_normalizada(embeddings.embed_documents([item.texto for item in itens]))
        similaridade_case = corpus @ case.T
        mais_parecida = similaridade_case.argmax(axis=1)
        maior = similaridade_case.max(axis=1)
        del similaridade_case

        indices_mantidos: list[int] = []
        for indice, item in enumerate(itens):
            trecho = limpar_html(item.dados["enunciado"])[:TAMANHO_TRECHO]
            if maior[indice] >= LIMIAR_SIMILARIDADE:
                self.descartar(
                    item.lote, item.linha, "igual_a_questao_do_case", trecho,
                    f"similaridade {maior[indice]:.3f}", ids_case[int(mais_parecida[indice])],
                )
                continue
            if indices_mantidos:
                similaridades = corpus[indices_mantidos] @ corpus[indice]
                melhor = int(similaridades.argmax())
                if similaridades[melhor] >= LIMIAR_SIMILARIDADE:
                    self.descartar(
                        item.lote, item.linha, "duplicata_embedding", trecho,
                        f"similaridade {similaridades[melhor]:.3f}", itens[indices_mantidos[melhor]].posicao,
                    )
                    continue
            indices_mantidos.append(indice)
        return [itens[i] for i in indices_mantidos]


def consolidar(
    pasta: Path,
    saida: Path,
    resumo: Path,
    embeddings: Embeddings | None = None,
    arvore: ArvoreTemas | None = None,
    questoes_case: pd.DataFrame | None = None,
) -> dict:
    """Lê os lotes, aplica as regras, grava o corpus e o resumo e devolve o resumo.

    `embeddings=None` pula a regra 5 (uso offline e testes).
    """
    arquivos = arquivos_de_lote(pasta)
    if not arquivos:
        raise SemLotesError(f"nenhum arquivo {PADRAO_LOTE} em {pasta}")
    if arvore is None:
        arvore = ArvoreTemas.carregar()
    consolidacao = _Consolidacao(arvore)

    chaves_vistas: dict[str, str] = {}
    itens: list[Item] = []
    for caminho in arquivos:
        itens.extend(consolidacao.ler_lote(caminho, chaves_vistas))

    if embeddings is not None:
        if questoes_case is None:
            questoes_case = carregar_questoes()
        itens = consolidacao.filtrar_por_embedding(itens, embeddings, questoes_case)

    corpus = [
        {"id": f"C{posicao:04d}", **item.dados, "lote": item.lote}
        for posicao, item in enumerate(itens, start=1)
    ]
    escrever_jsonl(Path(saida), corpus)

    dados_resumo = _montar_resumo(consolidacao, arquivos, corpus, embeddings is not None, Path(saida))
    Path(resumo).parent.mkdir(parents=True, exist_ok=True)
    Path(resumo).write_text(json.dumps(dados_resumo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dados_resumo


def _montar_resumo(consolidacao: _Consolidacao, arquivos: list[Path], corpus: list[dict], com_embeddings: bool, saida: Path) -> dict:
    mantidas_por_lote = Counter(q["lote"] for q in corpus)
    lotes = {}
    for caminho in arquivos:
        lote = nome_do_lote(caminho)
        motivos = consolidacao.motivos_por_lote.get(lote, Counter())
        lotes[lote] = {
            "lidas": consolidacao.lidas[lote],
            "mantidas": mantidas_por_lote[lote],
            "descartadas": {m: motivos[m] for m in MOTIVOS if motivos[m]},
        }
    total_motivos = Counter(d["motivo"] for d in consolidacao.descartadas)
    por_tema = Counter(q["tema_id"] for q in corpus)
    por_confianca = Counter(q["confianca_fonte"] for q in corpus)
    ordem_lote = {nome_do_lote(caminho): indice for indice, caminho in enumerate(arquivos)}
    descartadas = sorted(consolidacao.descartadas, key=lambda d: (ordem_lote[d["lote"]], d["linha"]))
    return {
        "arquivos": [caminho.name for caminho in arquivos],
        "saida": str(saida),
        "embeddings": com_embeddings,
        "limiar_similaridade": LIMIAR_SIMILARIDADE,
        "minimo_enunciado": MINIMO_ENUNCIADO,
        "lotes": lotes,
        "total_lidas": sum(consolidacao.lidas.values()),
        "total_mantidas": len(corpus),
        "descartadas_por_motivo": {m: total_motivos[m] for m in MOTIVOS},
        "por_tema": {str(tema): por_tema[tema] for tema in sorted(por_tema)},
        "por_confianca": {nivel: por_confianca[nivel] for nivel in CONFIANCAS},
        "temas_canonicalizados": consolidacao.canonicalizados,
        "descartadas": descartadas,
    }


_COLUNAS = [
    ("schema", "schema"),
    ("tema", "tema_nao_publicavel"),
    ("curto", "enunciado_curto"),
    ("dup_texto", "duplicata_texto"),
    ("igual_case", "igual_a_questao_do_case"),
    ("dup_embed", "duplicata_embedding"),
]


def formatar_resumo(resumo: dict) -> str:
    """Tabela por lote, totais e distribuição, para o terminal."""
    cabecalho = ["lote", "lidas", "mantidas"] + [rotulo for rotulo, _ in _COLUNAS]
    linhas = []
    for lote, dados in resumo["lotes"].items():
        linhas.append([lote, dados["lidas"], dados["mantidas"]] + [dados["descartadas"].get(m, 0) for _, m in _COLUNAS])
    linhas.append(
        ["total", resumo["total_lidas"], resumo["total_mantidas"]]
        + [resumo["descartadas_por_motivo"][m] for _, m in _COLUNAS]
    )
    larguras = [max(len(str(celula)) for celula in coluna) for coluna in zip(cabecalho, *linhas)]

    def formatar(celulas: list) -> str:
        primeira = str(celulas[0]).ljust(larguras[0])
        resto = [str(c).rjust(larguras[i]) for i, c in enumerate(celulas[1:], start=1)]
        return "  ".join([primeira, *resto])

    confianca = ", ".join(f"{nivel} {n}" for nivel, n in resumo["por_confianca"].items())
    comparacao = "feita" if resumo["embeddings"] else "pulada (--sem-embeddings)"
    saida = [
        "Consolidação do corpus de referência",
        "",
        formatar(cabecalho),
        *(formatar(linha) for linha in linhas),
        "",
        "Colunas de descarte: schema = formato; tema = tema não publicável; curto = enunciado com menos de "
        f"{resumo['minimo_enunciado']} caracteres; dup_texto = texto repetido; igual_case = igual a uma das 359; "
        "dup_embed = repetida por embedding.",
        f"Mantidas: {resumo['total_mantidas']} questões em {len(resumo['por_tema'])} temas, gravadas em {resumo['saida']}.",
        f"Confiança da fonte: {confianca}.",
        f"Temas canonicalizados: {len(resumo['temas_canonicalizados'])}.",
        f"Comparação por embedding (limiar {resumo['limiar_similaridade']}): {comparacao}.",
    ]
    return "\n".join(saida)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="consolidar_corpus",
        description="Consolida os lotes de data/coleta no corpus de referência (data/corpus_referencia.jsonl).",
    )
    parser.add_argument("--pasta", type=Path, default=PASTA_COLETA, help="pasta com os lote-*.jsonl")
    parser.add_argument("--saida", type=Path, default=CAMINHOS.corpus, help="JSONL do corpus consolidado")
    parser.add_argument("--resumo", type=Path, default=RESUMO, help="JSON com o resumo da consolidação")
    parser.add_argument(
        "--sem-embeddings", action="store_true",
        help="pula a comparação por embedding com as 359 e entre questões do corpus (uso offline)",
    )
    args = parser.parse_args(argv)

    if not arquivos_de_lote(args.pasta):
        print(f"Nenhum arquivo {PADRAO_LOTE} em {args.pasta}.", file=sys.stderr)
        return 1
    embeddings = None if args.sem_embeddings else criar_embeddings()
    try:
        resumo = consolidar(args.pasta, args.saida, args.resumo, embeddings=embeddings)
    except ChaveAusenteError as erro:
        print(f"{erro}\nNada foi gravado. Use --sem-embeddings para pular a comparação por embedding.", file=sys.stderr)
        return 2
    print(formatar_resumo(resumo))
    print(f"Resumo detalhado: {args.resumo}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
