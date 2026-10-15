"""O notebook da análise exploratória existe, é válido, foi executado e roda em
outra máquina: sem caminho absoluto, sem kernel registrado à mão e em sincronia
com o construtor."""
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
_TIPOS_DE_TEXTO = ("text/plain", "text/html", "text/markdown")


@cache
def _ler() -> nbformat.NotebookNode:
    assert NOTEBOOK.exists(), f"{NOTEBOOK.relative_to(RAIZ)} não existe"
    return nbformat.read(NOTEBOOK, as_version=4)


def _celulas(tipo: str) -> list:
    return [celula for celula in _ler().cells if celula.cell_type == tipo]


def _textos_das_saidas(celula) -> list[str]:
    textos = []
    for saida in celula.get("outputs", []):
        if saida.output_type == "stream":
            textos.append(saida.text)
        elif saida.output_type in ("execute_result", "display_data"):
            textos.extend(str(saida.data[tipo]) for tipo in _TIPOS_DE_TEXTO if tipo in saida.data)
        elif saida.output_type == "error":
            textos.append("\n".join(saida.traceback))
    return textos


def test_notebook_existe():
    assert NOTEBOOK.exists()


def test_notebook_e_nbformat_valido():
    nbformat.validate(_ler())


def test_tem_as_sete_secoes_numeradas():
    numeros = [int(n) for celula in _celulas("markdown") for n in _SECAO.findall(celula.source)]
    assert len(numeros) >= 7
    assert set(range(1, 8)) <= set(numeros)


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


def test_nenhuma_saida_ou_markdown_tem_caminho_absoluto():
    textos = [celula.source for celula in _celulas("markdown")]
    textos += [texto for celula in _celulas("code") for texto in _textos_das_saidas(celula)]
    assert not [texto[:200] for texto in textos if _CAMINHO_ABSOLUTO.search(texto)]


def test_primeira_celula_de_codigo_acha_a_raiz_pelo_pyproject():
    primeira = _celulas("code")[0].source
    assert "pyproject.toml" in primeira
    assert "Path.cwd()" in primeira
    assert "sys.path.insert" in primeira


def test_comando_de_reconstrucao_documentado_no_topo():
    topo = _ler().cells[0]
    assert topo.cell_type == "markdown"
    assert "uv run python analise/construir_notebook.py" in topo.source
    assert "uv run jupyter nbconvert --to notebook --execute --inplace analise/analise_exploratoria.ipynb" in topo.source


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


def test_notebook_em_sincronia_com_o_construtor():
    from analise.construir_notebook import montar_notebook

    esperado = [(celula.cell_type, celula.source) for celula in montar_notebook().cells]
    gravado = [(celula.cell_type, celula.source) for celula in _ler().cells]
    assert gravado == esperado
