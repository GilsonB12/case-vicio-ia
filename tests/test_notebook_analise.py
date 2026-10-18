"""O notebook da análise exploratória existe, é válido, foi executado e roda em
outra máquina: sem caminho absoluto e sem kernel registrado à mão."""
from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import nbformat

RAIZ = Path(__file__).resolve().parents[1]
NOTEBOOK = RAIZ / "analise" / "analise_exploratoria.ipynb"
TAMANHO_MAXIMO = 5 * 1024 * 1024
MAXIMO_DE_GRAFICOS = 5

_SECAO = re.compile(r"^## (\d+)\. ", re.MULTILINE)
_CAMINHO_ABSOLUTO = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
_CAMINHO_ABSOLUTO_NO_JSON = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\\\|/)")


@cache
def _ler() -> nbformat.NotebookNode:
    assert NOTEBOOK.exists(), f"{NOTEBOOK.relative_to(RAIZ)} não existe"
    return nbformat.read(NOTEBOOK, as_version=4)


def _celulas(tipo: str) -> list:
    return [celula for celula in _ler().cells if celula.cell_type == tipo]


def test_notebook_existe():
    assert NOTEBOOK.exists()


def test_notebook_e_nbformat_valido():
    nbformat.validate(_ler())


def test_tem_as_sete_secoes_numeradas_cada_uma_na_sua_celula():
    celulas_de_secao = [celula for celula in _celulas("markdown") if _SECAO.search(celula.source)]
    numeros = {int(n) for celula in celulas_de_secao for n in _SECAO.findall(celula.source)}
    assert len(celulas_de_secao) >= 7
    assert set(range(1, 8)) <= numeros


def test_toda_celula_de_codigo_foi_executada():
    codigo = _celulas("code")
    assert codigo, "o notebook não tem célula de código"
    nao_executadas = [i for i, celula in enumerate(codigo) if celula.execution_count is None]
    assert not nao_executadas, f"células de código sem execution_count: {nao_executadas}"


def test_nenhuma_saida_de_erro_ou_aviso():
    problemas = [
        (i, saida.output_type, saida.get("name"))
        for i, celula in enumerate(_celulas("code"))
        for saida in celula.outputs
        if saida.output_type == "error" or (saida.output_type == "stream" and saida.name == "stderr")
    ]
    assert not problemas


def test_nenhuma_celula_de_codigo_tem_caminho_absoluto():
    com_caminho = [i for i, celula in enumerate(_celulas("code")) if _CAMINHO_ABSOLUTO.search(celula.source)]
    assert not com_caminho


def test_arquivo_inteiro_sem_caminho_absoluto():
    # Texto bruto do .ipynb, metadados e saídas incluídos. No JSON a barra invertida vem
    # escapada ("D:\\Projetos"); o "\n" escapado depois de "Comando:" fica de fora porque
    # a letra antes dos dois-pontos tem outra letra antes dela. Base64 não tem ":".
    bruto = NOTEBOOK.read_text(encoding="utf-8")
    assert not [m.group(0) for m in _CAMINHO_ABSOLUTO_NO_JSON.finditer(bruto)]


def test_primeira_celula_de_codigo_acha_a_raiz_pelo_pyproject():
    primeira = _celulas("code")[0].source
    assert "pyproject.toml" in primeira
    assert "Path.cwd()" in primeira
    assert "sys.path.insert" in primeira



def test_kernel_e_o_padrao_do_ipykernel():
    assert _ler().metadata.kernelspec.name == "python3"


def test_graficos_embutidos_no_maximo_cinco():
    graficos = sum(
        "image/png" in saida.get("data", {})
        for celula in _celulas("code")
        for saida in celula.outputs
    )
    assert 1 <= graficos <= MAXIMO_DE_GRAFICOS


def test_tamanho_abaixo_de_5_mb():
    assert NOTEBOOK.stat().st_size < TAMANHO_MAXIMO
