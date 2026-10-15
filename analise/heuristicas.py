"""Heurísticas da análise exploratória: corrupção de OCR, enunciados genéricos e
repetidos, defeitos da árvore de temas e questões fora do escopo."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable

import pandas as pd

from classificador.dados import carregar_temas, limpar_html

_TOKEN = re.compile(r"[a-z]{3,}")
_ESPACOS = re.compile(r"\s+")

# Formas de enunciado que não dizem nada sobre o tema; o conteúdo está nas alternativas.
# "assinale a afirmativa" não está na lista do plano, mas aparece no dataset
# ("Assinale a afirmativa incorreta.") e é tão vazia quanto as outras.
_ENUNCIADO_GENERICO = re.compile(
    r"^(assinale a (alternativa|opcao|afirmativa)|marque a|analise a opcao|julgue o item)\b"
)
_TAMANHO_MAXIMO_GENERICO = 60

DISCIPLINAS_NO_ESCOPO = frozenset({
    "Penal",
    "Direito Penal",
    "Processo Penal",
    "Direito Processual Penal",
    "Direito Penal - Legislação Especial",
    "Criminologia",
})

TRECHOS_DE_TITULO_COM_ERRO = (
    "Estaturo",
    "Comeptência",
    "Crimonológicas",
    "Crimescontra",
    "Falso Testemunha",
    "Testemunhavel",
    "Caractéristas",
)

# "0 questões" sem dígito antes, para não confundir com "50 questões" ou "130 questões".
_ZERO_QUESTOES = re.compile(r"(?<!\d)0 questões")

# Acima de U+024F (fim do Latim Estendido-B) só esta pontuação tipográfica é aceita.
# Acentos do português, "§", "°", "º" e "ª" ficam abaixo desse limite.
_ULTIMO_LATINO = 0x024F
_PONTUACAO_PERMITIDA = frozenset("–—‘’‚“”„…•")

ORDEM_DOS_DEFEITOS = (
    "duplicado_sem_descricao",
    "inativo",
    "zero_questoes",
    "titulo_com_erro",
    "descricao_com_caracteres_estranhos",
)


def remover_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Minúsculo, sem acento, espaços colapsados."""
    return _ESPACOS.sub(" ", remover_acentos(texto).lower()).strip()


def tokens(texto: str) -> list[str]:
    """Tokens alfabéticos com 3 ou mais letras, minúsculos e sem acento."""
    return _TOKEN.findall(remover_acentos(texto or "").lower())


def _frequencia_por_texto(conjuntos: Iterable[set[str]]) -> Counter:
    frequencia: Counter = Counter()
    for conjunto in conjuntos:
        frequencia.update(conjunto)
    return frequencia


def montar_vocabulario(textos: Iterable[str]) -> set[str]:
    """Tokens que aparecem em pelo menos 2 textos distintos."""
    frequencia = _frequencia_por_texto(set(tokens(texto)) for texto in textos)
    return {token for token, n in frequencia.items() if n >= 2}


def proporcao_fora_do_vocabulario(texto: str, vocabulario: set[str]) -> float:
    """Fração dos tokens do texto, contando repetições, que não estão no vocabulário."""
    lista = tokens(texto)
    if not lista:
        return 0.0
    return sum(token not in vocabulario for token in lista) / len(lista)


def marcar_corrupcao_ocr(
    questoes: pd.DataFrame,
    limiar: float = 0.25,
    *,
    temas: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Proporção de tokens fora do vocabulário por questão, maior primeiro.

    O vocabulário de cada questão vem dos textos das demais questões mais os caminhos
    e descrições dos temas. A conta é feita uma vez: um token de outra questão segue
    no vocabulário enquanto aparecer em 2 textos sem contar a própria questão.
    """
    if temas is None:
        temas = carregar_temas()
    conjuntos_questoes = [set(tokens(texto)) for texto in questoes["texto"]]
    textos_temas = list(temas["caminho"]) + list(temas["descricao"])
    frequencia = _frequencia_por_texto(
        conjuntos_questoes + [set(tokens(texto)) for texto in textos_temas]
    )
    vocabulario_total = {token for token, n in frequencia.items() if n >= 2}

    proporcoes = []
    for texto, conjunto in zip(questoes["texto"], conjuntos_questoes):
        so_com_a_propria = {token for token in conjunto if frequencia[token] == 2}
        vocabulario = vocabulario_total - so_com_a_propria
        proporcoes.append(proporcao_fora_do_vocabulario(texto, vocabulario))

    resultado = pd.DataFrame({"id": list(questoes["id"]), "proporcao": proporcoes})
    resultado["suspeita"] = resultado["proporcao"] > limiar
    return resultado.sort_values(
        ["proporcao", "id"], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)


def eh_enunciado_generico(enunciado_limpo: str) -> bool:
    """Enunciado curto do tipo "Assinale a alternativa correta", sem conteúdo próprio."""
    enunciado = (enunciado_limpo or "").strip()
    if not enunciado or len(enunciado) > _TAMANHO_MAXIMO_GENERICO:
        return False
    return _ENUNCIADO_GENERICO.match(normalizar(enunciado)) is not None


def grupos_de_enunciado_repetido(questoes: pd.DataFrame) -> list[list[str]]:
    """Ids com o mesmo enunciado limpo e normalizado; maiores grupos primeiro."""
    grupos: dict[str, list[str]] = {}
    for id_questao, enunciado_html in zip(questoes["id"], questoes["enunciado_html"]):
        chave = normalizar(limpar_html(enunciado_html))
        grupos.setdefault(chave, []).append(id_questao)
    repetidos = [sorted(ids) for ids in grupos.values() if len(ids) >= 2]
    return sorted(repetidos, key=lambda ids: (-len(ids), ids[0]))


def _tem_caractere_estranho(texto: str) -> bool:
    return any(ord(c) > _ULTIMO_LATINO and c not in _PONTUACAO_PERMITIDA for c in texto)


def _defeitos_do_tema(tema) -> list[str]:
    descricao = tema.descricao or ""
    defeitos = []
    if not descricao.strip() and not pd.isna(tema.parent_id):
        defeitos.append("duplicado_sem_descricao")
    if not tema.ativo:
        defeitos.append("inativo")
    if _ZERO_QUESTOES.search(descricao):
        defeitos.append("zero_questoes")
    if any(trecho in tema.titulo for trecho in TRECHOS_DE_TITULO_COM_ERRO):
        defeitos.append("titulo_com_erro")
    if _tem_caractere_estranho(descricao):
        defeitos.append("descricao_com_caracteres_estranhos")
    return defeitos


def defeitos_da_arvore(temas: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por tema e defeito; um tema pode aparecer em mais de uma linha."""
    linhas = [
        {"tema_id": int(tema.tema_id), "titulo": tema.titulo, "defeito": defeito}
        for tema in temas.itertuples(index=False)
        for defeito in _defeitos_do_tema(tema)
    ]
    resultado = pd.DataFrame(linhas, columns=["tema_id", "titulo", "defeito"])
    ordem = {defeito: posicao for posicao, defeito in enumerate(ORDEM_DOS_DEFEITOS)}
    return (
        resultado.assign(_ordem=resultado["defeito"].map(ordem))
        .sort_values(["_ordem", "tema_id"], kind="stable")
        .drop(columns="_ordem")
        .reset_index(drop=True)
    )


def questoes_fora_do_escopo(questoes: pd.DataFrame) -> pd.DataFrame:
    """Questões cuja disciplina de origem não é penal, processual penal ou criminologia."""
    fora = questoes[~questoes["disciplina_origem"].str.strip().isin(DISCIPLINAS_NO_ESCOPO)]
    return pd.DataFrame({
        "id": fora["id"],
        "disciplina_origem": fora["disciplina_origem"],
        "assunto_origem": fora["assunto_origem"],
        "inicio": fora["texto"].str[:120],
    }).reset_index(drop=True)
