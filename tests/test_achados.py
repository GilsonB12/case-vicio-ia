"""O documento de achados tem as oito seções na ordem do plano e só cita ids que
existem nos anexos e aparecem no notebook executado.

Convenção do documento: questão é sempre Q seguido de 4 dígitos (Q0078); tema é
sempre "tema 4696" ou "temas 5078 e 5234" (lista colada à palavra, separada por
", ", " e ", " ou " ou " a "), ou fica numa coluna de tabela chamada `tema_id`.
Só essas formas são lidas como tema, então contagens como 359 e anos não colidem;
e um número de 4 dígitos na faixa dos temas fora dessas formas reprova o teste,
para nenhum id escapar da conferência.
"""
from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import nbformat

from classificador.dados import carregar_questoes, carregar_temas

RAIZ = Path(__file__).resolve().parents[1]
ACHADOS = RAIZ / "analise" / "achados.md"
NOTEBOOK = RAIZ / "analise" / "analise_exploratoria.ipynb"

SECOES = [
    "## 1. Resumo",
    "## 2. Os dados",
    "## 3. A árvore de temas",
    "## 4. As lixeiras",
    "## 5. Casos destacados",
    "## 6. Corrupção de OCR",
    "## 7. O que isso muda no pipeline",
    "## 8. O que fica para depois da execução",
]
MENOR_TEMA, MAIOR_TEMA = 4365, 6738
COLUNA_DE_TEMA = "tema_id"

_QUESTAO = re.compile(r"\bQ\d{4}\b")
_TEMA_NA_PROSA = re.compile(r"\b[Tt]emas? (\d{4}(?:(?:, | e | ou | a )\d{4})*)\b")
_QUATRO_DIGITOS = re.compile(r"\d{4}")
# Número isolado: não faz parte de outro número, de decimal com vírgula nem de "9.605/98".
_NUMERO_ISOLADO = re.compile(r"(?<![\w.,/])(\d{4})(?!\w|[.,/]\d)")
_DECIMAL_COM_PONTO = re.compile(r"(?<![\w.])0\.\d")
_DECIMAL_COM_VIRGULA = re.compile(r"(?<![\d,])0,\d+")
_EXEMPLO = re.compile(r"^- Q\d{4}: ", re.MULTILINE)
ASSUNTOS_DAS_LIXEIRAS = 6
EXEMPLOS_POR_ASSUNTO = 3
BULLETS_DO_RESUMO = 5


@cache
def _texto() -> str:
    assert ACHADOS.exists(), f"{ACHADOS.relative_to(RAIZ)} não existe"
    return ACHADOS.read_text(encoding="utf-8")


def _secao(numero: int) -> str:
    texto = _texto()
    inicio = texto.index(SECOES[numero - 1])
    fim = texto.index(SECOES[numero]) if numero < len(SECOES) else len(texto)
    return texto[inicio:fim]


def _celulas(linha: str) -> list[str]:
    return [celula.strip() for celula in linha.strip().strip("|").split("|")]


@cache
def _separar() -> tuple[tuple[int, ...], str]:
    """Ids de tema citados pela convenção, e o texto que sobra sem eles."""
    citados: list[int] = []
    resto: list[str] = []
    coluna: int | None = None
    for linha in _texto().splitlines():
        if not linha.lstrip().startswith("|"):
            coluna = None
        else:
            celulas = _celulas(linha)
            nomes = [celula.strip("`") for celula in celulas]
            if COLUNA_DE_TEMA in nomes:
                coluna = nomes.index(COLUNA_DE_TEMA)
            elif coluna is not None and coluna < len(celulas) and not set(celulas[coluna]) <= set("-: "):
                citados += [int(n) for n in _QUATRO_DIGITOS.findall(celulas[coluna])]
                celulas[coluna] = ""
                linha = "| " + " | ".join(celulas) + " |"
        for lista in _TEMA_NA_PROSA.findall(linha):
            citados += [int(n) for n in _QUATRO_DIGITOS.findall(lista)]
        resto.append(_TEMA_NA_PROSA.sub("", linha))
    return tuple(citados), "\n".join(resto)


@cache
def _texto_do_notebook() -> str:
    # Fontes das células e saídas em texto; as imagens em base64 ficam de fora.
    partes = []
    for celula in nbformat.read(NOTEBOOK, as_version=4).cells:
        partes.append(celula.source)
        for saida in celula.get("outputs", []):
            if saida.output_type == "stream":
                partes.append(saida.text)
            for tipo in ("text/plain", "text/markdown", "text/html"):
                if tipo in saida.get("data", {}):
                    partes.append(saida.data[tipo])
    return "\n".join(partes)


def test_achados_existe():
    assert ACHADOS.exists()


def test_tem_as_oito_secoes_na_ordem():
    titulos = [linha.rstrip() for linha in _texto().splitlines() if linha.startswith("## ")]
    assert titulos == SECOES


def test_toda_questao_citada_existe():
    citadas = set(_QUESTAO.findall(_texto()))
    assert citadas, "o documento não cita nenhuma questão"
    inexistentes = citadas - set(carregar_questoes()["id"])
    assert not inexistentes, f"questões citadas que não existem: {sorted(inexistentes)}"


def test_todo_tema_citado_existe():
    citados = set(_separar()[0])
    assert citados, "o documento não cita nenhum tema"
    inexistentes = citados - set(carregar_temas()["tema_id"])
    assert not inexistentes, f"temas citados que não existem: {sorted(inexistentes)}"


def test_numero_na_faixa_dos_temas_so_aparece_pela_convencao():
    soltos = [int(n) for n in _NUMERO_ISOLADO.findall(_separar()[1]) if MENOR_TEMA <= int(n) <= MAIOR_TEMA]
    assert not soltos, f"números com cara de tema fora da convenção (use 'tema N' ou a coluna tema_id): {soltos}"


def test_todo_id_citado_aparece_no_notebook():
    notebook = _texto_do_notebook()
    ids = sorted(set(_QUESTAO.findall(_texto()))) + [str(n) for n in sorted(set(_separar()[0]))]
    ausentes = [i for i in ids if not re.search(rf"\b{i}\b", notebook)]
    assert not ausentes, f"ids citados que o notebook não mostra: {ausentes}"


def test_proporcoes_com_virgula_decimal():
    assert not _DECIMAL_COM_PONTO.findall(_texto())


def test_todo_decimal_citado_aparece_no_notebook():
    notebook = _texto_do_notebook()
    citados = sorted(set(_DECIMAL_COM_VIRGULA.findall(_texto())))
    assert citados, "o documento não cita nenhuma proporção"
    ausentes = [d for d in citados if not re.search(rf"(?<![\d,]){re.escape(d)}(?!\d)", notebook)]
    assert not ausentes, f"proporções citadas que o notebook não mostra: {ausentes}"


def test_resumo_tem_cinco_bullets():
    bullets = [linha for linha in _secao(1).splitlines() if linha.startswith("- ")]
    assert len(bullets) == BULLETS_DO_RESUMO


def test_lixeiras_tem_tres_exemplos_por_assunto():
    # Cada assunto abre com uma linha em negrito ("**Concurso de Crimes** (43 questões)...")
    # seguida dos exemplos "- Q0039: ...".
    blocos = re.split(r"^\*\*", _secao(4), flags=re.MULTILINE)[1:]
    exemplos = {bloco.split("**")[0]: len(_EXEMPLO.findall(bloco)) for bloco in blocos}
    assert len(exemplos) == ASSUNTOS_DAS_LIXEIRAS, exemplos
    assert all(n == EXEMPLOS_POR_ASSUNTO for n in exemplos.values()), exemplos
