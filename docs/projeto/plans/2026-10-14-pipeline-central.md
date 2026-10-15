# Pipeline central de classificação: plano de implementação


**Goal:** Construir o pipeline que lê as 359 questões e os 377 temas, gera candidatos, colhe três votos, aplica as regras de decisão, calibra limiares e escreve `publicacao.csv` e `previsao.txt`.

**Architecture:** Pacote Python `classificador` em `src/`, com um módulo por etapa e um CLI que encadeia tudo. Cada etapa lê e grava arquivos JSONL em `data/intermediarios/`, então qualquer etapa pode ser rodada de novo isoladamente. Toda chamada a modelo e a embedding passa por cache em disco. Weaviate em Docker é o índice vetorial; um índice em memória com NumPy substitui quando o Weaviate não responde.

**Tech Stack:** Python 3.12 via uv, pandas, numpy, pydantic v2, beautifulsoup4, langchain-core, langchain-openai, langchain-anthropic, weaviate-client v4, pytest. Docker Compose para o Weaviate.

**Spec:** `docs/projeto/specs/2026-10-14-classificacao-topicos-design.md`


## Global Constraints

- Python `>=3.12,<3.13`, gerenciado por uv. Nunca usar o 3.14 da máquina.
- Todo código, comentário, docstring, nome de arquivo, mensagem de commit e texto de prompt em português. Nomes de identificadores em português sem acento.
- Modelos de linguagem via LangChain (`langchain-openai`, `langchain-anthropic`) com `with_structured_output` e schema Pydantic. Embeddings via `langchain-openai`.
- Desvio registrado da spec: o Weaviate é acessado pelo cliente oficial v4 e não pelo wrapper do LangChain, porque o wrapper esconde a métrica de similaridade. Os vetores vêm dos embeddings do LangChain.
- Temperatura zero onde o provedor permite. Não passar `temperature` para modelos da família GPT-5, que só aceitam o valor padrão.
- Toda chamada a modelo e a embedding passa por cache em `data/cache/`, chaveado por SHA-256 do conteúdo e do modelo. O cache é commitado.
- Sem chave de API e sem cache para uma entrada, o código falha com `ChaveAusenteError` e mensagem clara. Nunca falha em silêncio.
- Nenhuma linha de `publicacao.csv` tem `tema_central_id` nos 20 temas duplicados (ids 6716 a 6738) nem na raiz de disciplina (4365, 4683, 5062, 5465) nem em tema inativo (5078, 5234).
- Semente fixa `42` em tudo que sorteia.
- Caminhos de dados: entrada em `anexos/`, intermediários em `data/intermediarios/`, cache em `data/cache/`, saídas finais na raiz do repositório.
- Testes nunca chamam API real. Fakes em `tests/fakes.py`.
- Commits pequenos, mensagem em português, sem linhas de atribuição.

## Review Focus

1. Questão cujas alternativas são só "Certo" e "Errado" ou cujo enunciado é "Assinale a alternativa correta": o texto de classificação precisa carregar as alternativas, senão o modelo classifica no escuro. Teste na Tarefa 2.
2. Modelo devolve `tema_central_id` que não está entre os candidatos, ou um id inativo ou duplicado: o voto é rejeitado, há uma retentativa, e se persistir a questão cai na regra 7 em vez de publicar num tema inválido. Testes nas Tarefas 8 e 10.
3. Arquivo de cache corrompido ou truncado: tratado como ausência de cache e regravado, nunca derruba o pipeline. Testes nas Tarefas 4 e 8.
4. Dois modelos escolhem dois temas de nível 1 diferentes: isso não é "mesmo ramo", e a regra 3 nunca pode publicar na raiz da disciplina. Teste na Tarefa 10.
5. `publicacao.csv` com id repetido, id faltando, ou `tema_central_id` vazio em `publicar`: o validador acusa antes de gravar a versão final. Teste na Tarefa 11.

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `pyproject.toml`, `.python-version`, `docker-compose.yml` | Projeto, versão do Python, Weaviate local |
| `src/classificador/__init__.py` | Vazio |
| `src/classificador/config.py` | Caminhos e variáveis de ambiente num só lugar |
| `src/classificador/dados.py` | Limpeza de HTML, texto de classificação, carga de questões, temas e corpus |
| `src/classificador/arvore.py` | `ArvoreTemas`: navegação, canonicalização, régua de acerto |
| `src/classificador/embeddings.py` | `EmbeddingsComCache` sobre `OpenAIEmbeddings` |
| `src/classificador/indice.py` | Protocolo `Indice`, `IndiceMemoria`, `IndiceWeaviate`, `criar_indice` |
| `src/classificador/candidatos.py` | União das fontes de candidatos, duas passadas, CLI |
| `src/classificador/ancora.py` | Planilha da âncora manual |
| `src/classificador/llm.py` | Schema `VotoModelo`, prompt, cache, retentativas, dois classificadores |
| `src/classificador/prompts/classificar.md` | Prompt versionado |
| `src/classificador/vizinhanca.py` | Voto kNN sobre o corpus |
| `src/classificador/decisao.py` | As 7 regras |
| `src/classificador/saida.py` | Escrita e validação de `publicacao.csv` |
| `src/classificador/calibracao.py` | Faixas, reponderação, varredura, bootstrap, âncora, `previsao.txt` |
| `src/classificador/pipeline.py` | CLI `classificar` com subcomandos |
| `tests/fakes.py` | `EmbeddingsFalsas`, invocador falso de LLM |
| `tests/test_*.py` | Um arquivo por módulo |

Formatos dos intermediários, todos JSONL com uma linha por questão:

- `candidatos_<alvo>_p<1|2>.jsonl`: `{"id": "Q0001", "candidatos": [{"tema_id": 5524, "origem": "tema", "similaridade": 0.61}]}`. `origem` é `tema`, `corpus` ou `pai`.
- `votos_llm_<alvo>.jsonl`: `{"id": "Q0001", "openai": {...VotoModelo...} | null, "anthropic": {...} | null}`.
- `vizinhanca_<alvo>.jsonl`: `{"id": "Q0001", "tema_nivel2": 5527, "peso_nivel2": 0.55, "tema_nivel1": 5524, "peso_nivel1": 0.8, "vizinhos": [{"id": "C0001", "tema_id": 5527, "similaridade": 0.7}]}`.
- `decisoes_<alvo>.jsonl`: `{"id": "Q0001", "decisao": "publicar", "tema_central_id": 5524, "extras_ids": [5527], "confianca": 0.9, "motivo": "", "regra": 2}`.

`<alvo>` é `questoes` para as 359 ou `corpus` para o corpus de referência.

---

### Task 1: Esqueleto do projeto

**Files:**
- Create: `pyproject.toml`, `.python-version`, `docker-compose.yml`, `src/classificador/__init__.py`, `src/classificador/config.py`, `tests/__init__.py`, `tests/fakes.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `config.CAMINHOS` (dataclass com `anexos`, `questoes`, `temas`, `corpus`, `intermediarios`, `cache`, `ancora_planilha`, `ancora_manual`, `publicacao`, `previsao`) e `config.ler_env(nome, padrao)`.

- [ ] **Step 1: Criar `pyproject.toml`, `.python-version` e o pacote vazio**

```toml
[project]
name = "classificador-vicio"
version = "0.1.0"
description = "Classificação de questões jurídicas em temas, case Vício"
requires-python = ">=3.12,<3.13"
dependencies = [
  "pandas>=2.2",
  "numpy>=1.26",
  "pydantic>=2.7",
  "python-dotenv>=1.0",
  "beautifulsoup4>=4.12",
  "langchain-core>=0.3",
  "langchain-openai>=0.3",
  "langchain-anthropic>=0.3",
  "weaviate-client>=4.9",
]

[project.scripts]
classificar = "classificador.pipeline:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/classificador"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`.python-version` contém só `3.12`. Criar `src/classificador/__init__.py` e `tests/__init__.py` vazios.

- [ ] **Step 2: Instalar e verificar**

Run: `uv python install 3.12 && uv sync`
Expected: cria `.venv` com Python 3.12 e instala as dependências. Confirmar com `uv run python --version` mostrando `3.12.x`.

- [ ] **Step 3: Escrever o teste de configuração**

`tests/test_config.py`:

```python
from pathlib import Path

from classificador import config


def test_caminhos_apontam_para_dentro_do_repositorio():
    raiz = Path(__file__).resolve().parents[1]
    assert config.CAMINHOS.questoes == raiz / "anexos" / "questoes.jsonl"
    assert config.CAMINHOS.temas == raiz / "anexos" / "temas.csv"
    assert config.CAMINHOS.intermediarios == raiz / "data" / "intermediarios"
    assert config.CAMINHOS.cache == raiz / "data" / "cache"
    assert config.CAMINHOS.publicacao == raiz / "publicacao.csv"


def test_ler_env_devolve_padrao(monkeypatch):
    monkeypatch.delenv("VARIAVEL_INEXISTENTE", raising=False)
    assert config.ler_env("VARIAVEL_INEXISTENTE", "x") == "x"
    monkeypatch.setenv("VARIAVEL_INEXISTENTE", "y")
    assert config.ler_env("VARIAVEL_INEXISTENTE", "x") == "y"
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL com `ModuleNotFoundError` ou `AttributeError: CAMINHOS`.

- [ ] **Step 5: Implementar `config.py`**

```python
"""Caminhos do projeto e leitura de variáveis de ambiente."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")

SEMENTE = 42


@dataclass(frozen=True)
class Caminhos:
    anexos: Path
    questoes: Path
    temas: Path
    corpus: Path
    intermediarios: Path
    cache: Path
    ancora_planilha: Path
    ancora_manual: Path
    publicacao: Path
    previsao: Path
    prompts: Path


CAMINHOS = Caminhos(
    anexos=RAIZ / "anexos",
    questoes=RAIZ / "anexos" / "questoes.jsonl",
    temas=RAIZ / "anexos" / "temas.csv",
    corpus=RAIZ / "data" / "corpus_referencia.jsonl",
    intermediarios=RAIZ / "data" / "intermediarios",
    cache=RAIZ / "data" / "cache",
    ancora_planilha=RAIZ / "data" / "ancora_para_rotular.csv",
    ancora_manual=RAIZ / "data" / "ancora_manual.csv",
    publicacao=RAIZ / "publicacao.csv",
    previsao=RAIZ / "previsao.txt",
    prompts=RAIZ / "src" / "classificador" / "prompts",
)


def ler_env(nome: str, padrao: str | None = None) -> str | None:
    """Lê uma variável de ambiente; vazio conta como ausente."""
    valor = os.environ.get(nome)
    if valor is None or valor.strip() == "":
        return padrao
    return valor.strip()


class ChaveAusenteError(RuntimeError):
    """Chave de API ausente e sem cache para atender a chamada."""
```

- [ ] **Step 6: Escrever `tests/fakes.py`**

```python
"""Substitutos determinísticos para testes: nunca chamam API."""
from __future__ import annotations

import hashlib

import numpy as np
from langchain_core.embeddings import Embeddings

DIMENSAO_FALSA = 16


def vetor_falso(texto: str) -> list[float]:
    """Vetor determinístico a partir do SHA-256 do texto, normalizado."""
    resumo = hashlib.sha256(texto.encode("utf-8")).digest()
    bruto = np.frombuffer(resumo[:DIMENSAO_FALSA * 2], dtype=np.uint16).astype(np.float64)
    bruto = bruto - bruto.mean()
    norma = np.linalg.norm(bruto) or 1.0
    return (bruto / norma).tolist()


class EmbeddingsFalsas(Embeddings):
    """Embeddings determinísticos. Textos iguais dão vetores iguais."""

    def __init__(self) -> None:
        self.chamadas: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.chamadas.extend(texts)
        return [vetor_falso(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.chamadas.append(text)
        return vetor_falso(text)
```

- [ ] **Step 7: Criar `docker-compose.yml`**

```yaml
services:
  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.27.0
    ports:
      - "8080:8080"
      - "50051:50051"
    environment:
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"
      PERSISTENCE_DATA_PATH: /var/lib/weaviate
      DEFAULT_VECTORIZER_MODULE: none
      ENABLE_MODULES: ""
      CLUSTER_HOSTNAME: node1
    volumes:
      - weaviate_data:/var/lib/weaviate

volumes:
  weaviate_data: {}
```

- [ ] **Step 8: Rodar os testes e commitar**

Run: `uv run pytest -v`
Expected: 2 PASS.

```bash
git add pyproject.toml .python-version uv.lock docker-compose.yml src tests
git commit -m "Esqueleto do projeto com uv, config e fakes de teste"
```

---

### Task 2: Limpeza de HTML e carga de dados

**Files:**
- Create: `src/classificador/dados.py`, `tests/test_dados.py`

**Interfaces:**
- Produces:
  - `limpar_html(html: str) -> str`
  - `montar_texto(enunciado_html: str, comando: str, alternativas: dict[str, str]) -> str`
  - `carregar_questoes(caminho: Path = CAMINHOS.questoes) -> pd.DataFrame` com colunas `id, enunciado_html, comando, alternativas, disciplina_origem, assunto_origem, texto`
  - `carregar_temas(caminho: Path = CAMINHOS.temas) -> pd.DataFrame` com colunas do CSV mais `tema_id: int`, `parent_id: Int64`, `nivel: int`, `ativo: bool`
  - `carregar_corpus(caminho: Path = CAMINHOS.corpus) -> pd.DataFrame` com colunas `id, tema_id, enunciado, comando, alternativas, url, site, confianca_fonte, texto`
  - `ler_jsonl(caminho) -> list[dict]`, `escrever_jsonl(caminho, linhas: list[dict]) -> None`

- [ ] **Step 1: Escrever os testes**

`tests/test_dados.py`:

```python
import json

import pandas as pd

from classificador import dados
from classificador.config import CAMINHOS


def test_limpar_html_remove_tags_e_normaliza_espacos():
    html = "Texto <b>em negrito</b><br><br>linha &nbsp; nova  <i>it</i>"
    assert dados.limpar_html(html) == "Texto em negrito linha nova it"


def test_limpar_html_troca_barra_n_literal_por_espaco():
    assert dados.limpar_html("Ministério\\nPúblico") == "Ministério Público"


def test_montar_texto_inclui_comando_e_alternativas():
    texto = dados.montar_texto(
        "Assinale a alternativa correta.",
        "Sobre furto.",
        {"A": " furto simples ", "B": "roubo"},
    )
    assert texto == (
        "Assinale a alternativa correta.\n"
        "Comando: Sobre furto.\n"
        "Alternativas:\n"
        "A) furto simples\n"
        "B) roubo"
    )


def test_montar_texto_sem_comando_omite_linha_de_comando():
    texto = dados.montar_texto("Enunciado", "", {"C": "Certo", "E": "Errado"})
    assert texto == "Enunciado\nAlternativas:\nC) Certo\nE) Errado"


def test_carregar_questoes_le_as_359_com_texto():
    df = dados.carregar_questoes()
    assert len(df) == 359
    assert df["id"].is_unique
    assert set(["id", "texto", "alternativas", "disciplina_origem", "assunto_origem"]) <= set(df.columns)
    generica = df.set_index("id").loc["Q0090", "texto"]
    assert "Alternativas:" in generica and "A)" in generica


def test_carregar_temas_tipos_e_ativos():
    df = dados.carregar_temas()
    assert len(df) == 377
    assert df["tema_id"].dtype.kind == "i"
    assert df["nivel"].dtype.kind == "i"
    assert df["parent_id"].isna().sum() == 4
    assert (~df["ativo"]).sum() == 2
    assert set(df.loc[~df["ativo"], "tema_id"]) == {5078, 5234}


def test_jsonl_ida_e_volta(tmp_path):
    caminho = tmp_path / "x.jsonl"
    linhas = [{"id": "Q1", "v": [1, 2]}, {"id": "Q2", "v": None}]
    dados.escrever_jsonl(caminho, linhas)
    assert dados.ler_jsonl(caminho) == linhas


def test_carregar_corpus_monta_texto(tmp_path):
    caminho = tmp_path / "corpus.jsonl"
    caminho.write_text(json.dumps({
        "id": "C0001", "tema_id": 4704, "enunciado": "Sobre a Lei Maria da Penha",
        "comando": "", "alternativas": {"C": "Certo", "E": "Errado"},
        "url": "https://exemplo", "site": "exemplo", "confianca_fonte": "alta",
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    df = dados.carregar_corpus(caminho)
    assert list(df["id"]) == ["C0001"]
    assert df.loc[0, "texto"].startswith("Sobre a Lei Maria da Penha")
    assert df.loc[0, "tema_id"] == 4704
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_dados.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.dados`.

- [ ] **Step 3: Implementar `dados.py`**

```python
"""Carga e limpeza das questões, dos temas e do corpus."""
from __future__ import annotations

import html as modulo_html
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup

from classificador.config import CAMINHOS

_ESPACOS = re.compile(r"\s+")


def limpar_html(texto_html: str) -> str:
    """Remove tags, entidades e o '\\n' literal que vem do banco; colapsa espaços."""
    if not texto_html:
        return ""
    sem_tags = BeautifulSoup(texto_html, "html.parser").get_text(" ")
    sem_entidades = modulo_html.unescape(sem_tags).replace("\xa0", " ")
    sem_barra_n = sem_entidades.replace("\\n", " ")
    return _ESPACOS.sub(" ", sem_barra_n).strip()


def montar_texto(enunciado_html: str, comando: str, alternativas: dict[str, str]) -> str:
    """Texto que os modelos e os embeddings recebem: enunciado, comando e alternativas."""
    partes = [limpar_html(enunciado_html)]
    comando_limpo = limpar_html(comando or "")
    if comando_limpo:
        partes.append(f"Comando: {comando_limpo}")
    if alternativas:
        partes.append("Alternativas:")
        for letra, texto in alternativas.items():
            partes.append(f"{letra}) {limpar_html(texto)}")
    return "\n".join(partes)


def ler_jsonl(caminho: Path) -> list[dict]:
    with open(caminho, encoding="utf-8") as arquivo:
        return [json.loads(linha) for linha in arquivo if linha.strip()]


def escrever_jsonl(caminho: Path, linhas: list[dict]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as arquivo:
        for linha in linhas:
            arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")


def carregar_questoes(caminho: Path = CAMINHOS.questoes) -> pd.DataFrame:
    linhas = ler_jsonl(caminho)
    df = pd.DataFrame(linhas)
    df["comando"] = df["comando"].fillna("")
    df["disciplina_origem"] = df["disciplina_origem"].fillna("")
    df["assunto_origem"] = df["assunto_origem"].fillna("")
    df["texto"] = [
        montar_texto(e, c, a)
        for e, c, a in zip(df["enunciado_html"], df["comando"], df["alternativas"])
    ]
    return df


def carregar_temas(caminho: Path = CAMINHOS.temas) -> pd.DataFrame:
    df = pd.read_csv(caminho, dtype=str, keep_default_na=False)
    df["tema_id"] = df["tema_id"].astype(int)
    df["parent_id"] = pd.to_numeric(df["parent_id"].replace("", np.nan)).astype("Int64")
    df["nivel"] = df["nivel"].astype(int)
    df["ativo"] = df["status"].str.strip().str.lower() == "active"
    return df


def carregar_corpus(caminho: Path = CAMINHOS.corpus) -> pd.DataFrame:
    linhas = ler_jsonl(caminho)
    df = pd.DataFrame(linhas)
    if "comando" not in df.columns:
        df["comando"] = ""
    df["comando"] = df["comando"].fillna("")
    df["tema_id"] = df["tema_id"].astype(int)
    df["texto"] = [
        montar_texto(e, c, a)
        for e, c, a in zip(df["enunciado"], df["comando"], df["alternativas"])
    ]
    return df
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_dados.py -v`
Expected: 8 PASS. Se `test_carregar_temas_tipos_e_ativos` falhar na contagem de `parent_id` nulos, conferir se o `replace("", pd.NA)` está sendo aplicado antes do `to_numeric`.

- [ ] **Step 5: Commit**

```bash
git add src/classificador/dados.py tests/test_dados.py
git commit -m "Carga de questões, temas e corpus com limpeza de HTML"
```

---

### Task 3: Árvore de temas, canonicalização e régua de acerto

**Files:**
- Create: `src/classificador/arvore.py`, `tests/test_arvore.py`

**Interfaces:**
- Consumes: `dados.carregar_temas()`.
- Produces: classe `ArvoreTemas` com os métodos abaixo. Todos recebem e devolvem `int`.
  - `existe(tema_id) -> bool`, `titulo(tema_id) -> str`, `caminho(tema_id) -> str`, `descricao(tema_id) -> str`, `nivel(tema_id) -> int`, `disciplina(tema_id) -> str`, `ativo(tema_id) -> bool`
  - `pai(tema_id) -> int | None`, `filhos(tema_id) -> list[int]`, `irmaos(tema_id) -> list[int]`, `eh_raiz(tema_id) -> bool`
  - `ancestral_nivel1(tema_id) -> int` (nível 1 devolve ele mesmo; raiz levanta `ValueError`)
  - `mesmo_ramo(a, b) -> bool`
  - `eh_duplicado(tema_id) -> bool`, `canonico(tema_id) -> int`, `duplicados() -> dict[int, int]`
  - `publicavel(tema_id) -> bool` (ativo, não raiz, não duplicado)
  - `candidatos_possiveis() -> list[int]` (todos os publicáveis, ordenados)
  - `documento(tema_id) -> str` (caminho mais descrição sem a contagem e sem o "Path:")
  - `acerto(decidido, verdadeiro) -> bool` (igual, pai ou filho)
  - `ArvoreTemas.carregar() -> ArvoreTemas` (classmethod que usa `carregar_temas()`)
- Constantes: `EXCECOES_CANONICAS = {6735: 5543, 6736: 5560, 6722: 4696}`, `normalizar_titulo(titulo: str) -> str`.

- [ ] **Step 1: Escrever os testes**

`tests/test_arvore.py`:

```python
import pytest

from classificador.arvore import ArvoreTemas, normalizar_titulo

DUPLICADOS_ESPERADOS = {
    6716, 6717, 6718, 6719, 6720, 6721, 6722, 6723, 6724, 6725,
    6726, 6727, 6728, 6732, 6733, 6734, 6735, 6736, 6737, 6738,
}


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def test_normalizar_titulo_tira_acento_parte_e_caixa():
    assert normalizar_titulo("Dos Crimes Contra a Administração Pública (Parte 1)") == "dos crimes contra a administracao publica"
    assert normalizar_titulo("Teoria da Pena (Parte 2)") == "teoria da pena"


def test_duplicados_sao_exatamente_os_vinte(arvore):
    mapa = arvore.duplicados()
    assert set(mapa) == DUPLICADOS_ESPERADOS
    for origem, destino in mapa.items():
        assert not arvore.eh_duplicado(destino)
        assert arvore.ativo(destino)
        assert not arvore.eh_raiz(destino)


def test_canonicos_conhecidos(arvore):
    assert arvore.canonico(6724) == 4704
    assert arvore.canonico(6726) == 5199
    assert arvore.canonico(6727) == 5199
    assert arvore.canonico(6732) == 5480
    assert arvore.canonico(6735) == 5543
    assert arvore.canonico(6736) == 5560
    assert arvore.canonico(6722) == 4696
    assert arvore.canonico(6734) == 4703
    assert arvore.canonico(5159) == 5159


def test_navegacao_basica(arvore):
    assert arvore.pai(5527) == 5524
    assert 5527 in arvore.filhos(5524)
    assert 5528 in arvore.irmaos(5527)
    assert 5527 not in arvore.irmaos(5527)
    assert arvore.pai(5062) is None
    assert arvore.eh_raiz(5465)
    assert arvore.nivel(5527) == 2
    assert arvore.disciplina(5527) == "Processo Penal"


def test_ancestral_nivel1(arvore):
    assert arvore.ancestral_nivel1(5527) == 5524
    assert arvore.ancestral_nivel1(5524) == 5524
    with pytest.raises(ValueError):
        arvore.ancestral_nivel1(5465)


def test_mesmo_ramo(arvore):
    assert arvore.mesmo_ramo(5527, 5528)
    assert arvore.mesmo_ramo(5527, 5524)
    assert not arvore.mesmo_ramo(5524, 5543)
    assert not arvore.mesmo_ramo(5543, 5590)


def test_acerto_segue_a_regua_da_vicio(arvore):
    assert arvore.acerto(5527, 5527)
    assert arvore.acerto(5524, 5527)
    assert arvore.acerto(5527, 5524)
    assert not arvore.acerto(5527, 5528)
    assert not arvore.acerto(5524, 5543)


def test_publicavel_e_candidatos_possiveis(arvore):
    assert arvore.publicavel(4704)
    assert not arvore.publicavel(6724)
    assert not arvore.publicavel(5062)
    assert not arvore.publicavel(5078)
    possiveis = arvore.candidatos_possiveis()
    assert len(possiveis) == 377 - 4 - 2 - 20
    assert possiveis == sorted(possiveis)


def test_documento_sem_ruido_de_contagem(arvore):
    doc = arvore.documento(5159)
    assert doc.startswith("Penal > Dos Crimes Contra o Patrimônio > Furto")
    assert "no source" not in doc
    assert "Path:" not in doc
    assert arvore.documento(6724) == "Penal > Lei Maria da Penha"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_arvore.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.arvore`.

- [ ] **Step 3: Implementar `arvore.py`**

```python
"""Árvore de temas: navegação, canonicalização de duplicatas e régua de acerto."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

import pandas as pd

from classificador.dados import carregar_temas

EXCECOES_CANONICAS: dict[int, int] = {
    6735: 5543,  # "Provas em Espécie" -> "Provas em Espécies"
    6736: 5560,  # "Recursos (Parte 03) - Espécies" -> "Recursos em Espécies"
    6722: 4696,  # "Estatuto do Idoso - Crimes" -> "Estaturo de Idoso - Crimes"
}

_PARTE = re.compile(r"\(\s*parte\s*\d+\s*\)")
_CONTAGEM = re.compile(r"\s*\d+\s+quest(?:ões|oes)(?: no source)?\.?", re.IGNORECASE)
_PATH = re.compile(r"\s*Path:.*$", re.DOTALL)


def normalizar_titulo(titulo: str) -> str:
    """Minúsculo, sem acento, sem sufixo '(Parte N)', espaços colapsados."""
    sem_acento = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    sem_parte = _PARTE.sub("", sem_acento.lower())
    return re.sub(r"\s+", " ", sem_parte).strip()


class ArvoreTemas:
    def __init__(self, temas: pd.DataFrame) -> None:
        self._df = temas.set_index("tema_id", drop=False)
        self._filhos: dict[int, list[int]] = defaultdict(list)
        for tema_id, pai in zip(self._df["tema_id"], self._df["parent_id"]):
            if pd.notna(pai):
                self._filhos[int(pai)].append(int(tema_id))
        self._canonicos = self._montar_canonicos()

    @classmethod
    def carregar(cls) -> "ArvoreTemas":
        return cls(carregar_temas())

    def _linha(self, tema_id: int) -> pd.Series:
        try:
            return self._df.loc[int(tema_id)]
        except KeyError as erro:
            raise KeyError(f"tema {tema_id} não existe") from erro

    def _montar_canonicos(self) -> dict[int, int]:
        """Temas sem descrição são duplicatas; casam por título normalizado ou pela tabela de exceções."""
        por_titulo: dict[str, list[int]] = defaultdict(list)
        for tema_id, titulo, descricao in zip(self._df["tema_id"], self._df["titulo"], self._df["descricao"]):
            if descricao.strip():
                por_titulo[normalizar_titulo(titulo)].append(int(tema_id))
        mapa: dict[int, int] = {}
        for tema_id, titulo, descricao, nivel in zip(
            self._df["tema_id"], self._df["titulo"], self._df["descricao"], self._df["nivel"]
        ):
            tema_id = int(tema_id)
            if descricao.strip() or nivel == 0:
                continue
            if tema_id in EXCECOES_CANONICAS:
                mapa[tema_id] = EXCECOES_CANONICAS[tema_id]
                continue
            candidatos = por_titulo.get(normalizar_titulo(titulo), [])
            if len(candidatos) != 1:
                raise ValueError(f"tema duplicado {tema_id} '{titulo}' sem canônico único: {candidatos}")
            mapa[tema_id] = candidatos[0]
        return mapa

    def existe(self, tema_id: int) -> bool:
        return int(tema_id) in self._df.index

    def titulo(self, tema_id: int) -> str:
        return str(self._linha(tema_id)["titulo"])

    def caminho(self, tema_id: int) -> str:
        return str(self._linha(tema_id)["caminho"])

    def descricao(self, tema_id: int) -> str:
        return str(self._linha(tema_id)["descricao"])

    def nivel(self, tema_id: int) -> int:
        return int(self._linha(tema_id)["nivel"])

    def disciplina(self, tema_id: int) -> str:
        return str(self._linha(tema_id)["disciplina"])

    def ativo(self, tema_id: int) -> bool:
        return bool(self._linha(tema_id)["ativo"])

    def pai(self, tema_id: int) -> int | None:
        valor = self._linha(tema_id)["parent_id"]
        return None if pd.isna(valor) else int(valor)

    def filhos(self, tema_id: int) -> list[int]:
        return list(self._filhos.get(int(tema_id), []))

    def irmaos(self, tema_id: int) -> list[int]:
        pai = self.pai(tema_id)
        if pai is None:
            return []
        return [f for f in self.filhos(pai) if f != int(tema_id)]

    def eh_raiz(self, tema_id: int) -> bool:
        return self.nivel(tema_id) == 0

    def ancestral_nivel1(self, tema_id: int) -> int:
        nivel = self.nivel(tema_id)
        if nivel == 0:
            raise ValueError(f"tema {tema_id} é raiz de disciplina e não tem ancestral de nível 1")
        if nivel == 1:
            return int(tema_id)
        pai = self.pai(tema_id)
        assert pai is not None
        return pai

    def mesmo_ramo(self, a: int, b: int) -> bool:
        if self.eh_raiz(a) or self.eh_raiz(b):
            return False
        return self.ancestral_nivel1(a) == self.ancestral_nivel1(b)

    def eh_duplicado(self, tema_id: int) -> bool:
        return int(tema_id) in self._canonicos

    def canonico(self, tema_id: int) -> int:
        return self._canonicos.get(int(tema_id), int(tema_id))

    def duplicados(self) -> dict[int, int]:
        return dict(self._canonicos)

    def publicavel(self, tema_id: int) -> bool:
        return self.existe(tema_id) and self.ativo(tema_id) and not self.eh_raiz(tema_id) and not self.eh_duplicado(tema_id)

    def candidatos_possiveis(self) -> list[int]:
        return sorted(int(t) for t in self._df["tema_id"] if self.publicavel(int(t)))

    def documento(self, tema_id: int) -> str:
        descricao = _PATH.sub("", _CONTAGEM.sub("", self.descricao(tema_id))).strip()
        return f"{self.caminho(tema_id)}\n{descricao}" if descricao else self.caminho(tema_id)

    def acerto(self, decidido: int, verdadeiro: int) -> bool:
        """Régua da Vício: igual, pai ou filho do tema verdadeiro."""
        decidido, verdadeiro = int(decidido), int(verdadeiro)
        if decidido == verdadeiro:
            return True
        return self.pai(decidido) == verdadeiro or self.pai(verdadeiro) == decidido
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_arvore.py -v`
Expected: 10 PASS. Se `_montar_canonicos` levantar `ValueError`, imprimir os candidatos e conferir se algum tema fora do grupo 6716 a 6738 tem descrição vazia; nesse caso adicioná-lo à tabela de exceções com destino justificado em comentário.

- [ ] **Step 5: Commit**

```bash
git add src/classificador/arvore.py tests/test_arvore.py
git commit -m "Árvore de temas com canonicalização das 20 duplicatas e régua de acerto"
```

---

### Task 4: Embeddings com cache

**Files:**
- Create: `src/classificador/embeddings.py`, `tests/test_embeddings.py`

**Interfaces:**
- Consumes: `config.CAMINHOS.cache`, `config.ler_env`, `config.ChaveAusenteError`, `tests.fakes.EmbeddingsFalsas`.
- Produces:
  - `class EmbeddingsComCache(langchain_core.embeddings.Embeddings)` com `__init__(base: Embeddings | None, modelo: str, pasta_cache: Path)`, `embed_documents(texts) -> list[list[float]]`, `embed_query(text) -> list[float]`, atributos `chamadas_base: int` e `acertos_cache: int`.
  - `criar_embeddings(pasta_cache: Path = CAMINHOS.cache) -> EmbeddingsComCache`. Lê `MODELO_EMBEDDINGS` (padrão `text-embedding-3-large`) e `OPENAI_API_KEY`. Sem chave, `base` é `None` e só o cache responde.

- [ ] **Step 1: Escrever os testes**

`tests/test_embeddings.py`:

```python
import json

import pytest

from classificador.config import ChaveAusenteError
from classificador.embeddings import EmbeddingsComCache
from tests.fakes import EmbeddingsFalsas


def test_segunda_chamada_vem_do_cache(tmp_path):
    base = EmbeddingsFalsas()
    emb = EmbeddingsComCache(base, "falso", tmp_path)
    primeira = emb.embed_documents(["a", "b"])
    assert len(base.chamadas) == 2
    segunda = emb.embed_documents(["a", "b"])
    assert len(base.chamadas) == 2
    assert primeira == segunda
    assert emb.acertos_cache == 2


def test_mistura_de_acertos_e_faltas_preserva_ordem(tmp_path):
    base = EmbeddingsFalsas()
    emb = EmbeddingsComCache(base, "falso", tmp_path)
    emb.embed_documents(["b"])
    vetores = emb.embed_documents(["a", "b", "c"])
    assert vetores[0] == base.embed_documents(["a"])[0]
    assert vetores[1] == base.embed_documents(["b"])[0]
    assert vetores[2] == base.embed_documents(["c"])[0]


def test_sem_base_e_sem_cache_levanta_erro_claro(tmp_path):
    emb = EmbeddingsComCache(None, "falso", tmp_path)
    with pytest.raises(ChaveAusenteError, match="OPENAI_API_KEY"):
        emb.embed_query("x")


def test_sem_base_com_cache_funciona(tmp_path):
    EmbeddingsComCache(EmbeddingsFalsas(), "falso", tmp_path).embed_query("x")
    emb = EmbeddingsComCache(None, "falso", tmp_path)
    assert len(emb.embed_query("x")) == 16


def test_cache_corrompido_e_regravado(tmp_path):
    base = EmbeddingsFalsas()
    emb = EmbeddingsComCache(base, "falso", tmp_path)
    emb.embed_query("x")
    arquivo = next((tmp_path / "embeddings" / "falso").glob("*.json"))
    arquivo.write_text("{isso nao e json", encoding="utf-8")
    vetor = emb.embed_query("x")
    assert len(base.chamadas) == 2
    assert json.loads(arquivo.read_text(encoding="utf-8")) == vetor
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_embeddings.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.embeddings`.

- [ ] **Step 3: Implementar `embeddings.py`**

```python
"""Embeddings da OpenAI via LangChain, com cache em disco por texto."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from langchain_core.embeddings import Embeddings

from classificador.config import CAMINHOS, ChaveAusenteError, ler_env

MODELO_PADRAO = "text-embedding-3-large"


class EmbeddingsComCache(Embeddings):
    """Lê do cache o que já foi calculado; chama a base só para o que falta."""

    def __init__(self, base: Embeddings | None, modelo: str, pasta_cache: Path) -> None:
        self.base = base
        self.modelo = modelo
        self.pasta = pasta_cache / "embeddings" / modelo
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.chamadas_base = 0
        self.acertos_cache = 0

    def _arquivo(self, texto: str) -> Path:
        chave = hashlib.sha256(f"{self.modelo}\n{texto}".encode("utf-8")).hexdigest()
        return self.pasta / f"{chave}.json"

    def _ler(self, texto: str) -> list[float] | None:
        arquivo = self._arquivo(texto)
        if not arquivo.exists():
            return None
        try:
            vetor = json.loads(arquivo.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            arquivo.unlink()
            return None
        if not isinstance(vetor, list) or not vetor or not all(isinstance(x, (int, float)) for x in vetor):
            arquivo.unlink()
            return None
        return [float(x) for x in vetor]

    def _gravar(self, texto: str, vetor: list[float]) -> None:
        self._arquivo(texto).write_text(json.dumps(vetor), encoding="utf-8")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        resultado: list[list[float] | None] = [self._ler(t) for t in texts]
        self.acertos_cache += sum(1 for v in resultado if v is not None)
        faltantes = [i for i, v in enumerate(resultado) if v is None]
        if faltantes:
            if self.base is None:
                raise ChaveAusenteError(
                    f"{len(faltantes)} texto(s) sem embedding em cache e OPENAI_API_KEY ausente. "
                    "Defina a chave no .env ou use o cache commitado."
                )
            novos = self.base.embed_documents([texts[i] for i in faltantes])
            self.chamadas_base += len(faltantes)
            for indice, vetor in zip(faltantes, novos):
                vetor = [float(x) for x in vetor]
                self._gravar(texts[indice], vetor)
                resultado[indice] = vetor
        return [v for v in resultado if v is not None]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def criar_embeddings(pasta_cache: Path = CAMINHOS.cache) -> EmbeddingsComCache:
    modelo = ler_env("MODELO_EMBEDDINGS", MODELO_PADRAO) or MODELO_PADRAO
    base: Embeddings | None = None
    if ler_env("OPENAI_API_KEY"):
        from langchain_openai import OpenAIEmbeddings

        base = OpenAIEmbeddings(model=modelo)
    return EmbeddingsComCache(base, modelo, pasta_cache)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_embeddings.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/classificador/embeddings.py tests/test_embeddings.py
git commit -m "Embeddings da OpenAI com cache em disco e erro claro sem chave"
```

---

### Task 5: Índice vetorial com Weaviate e substituto em memória

**Files:**
- Create: `src/classificador/indice.py`, `tests/test_indice.py`

**Interfaces:**
- Consumes: `Embeddings` do LangChain (real ou `EmbeddingsFalsas`), `config.ler_env`.
- Produces:
  - `@dataclass(frozen=True) Resultado(id: str, metadados: dict, similaridade: float)`
  - `class Indice(Protocol)`: `nome: str`; `adicionar(ids: list[str], textos: list[str], metadados: list[dict]) -> None`; `buscar(texto: str, k: int, excluir: frozenset[str] = frozenset()) -> list[Resultado]` ordenado por similaridade decrescente; `tamanho() -> int`.
  - `class IndiceMemoria(nome, embeddings)` e `class IndiceWeaviate(nome, embeddings, cliente)`, ambos cumprindo `Indice`. `IndiceWeaviate.fechar()` fecha o cliente.
  - `conectar_weaviate() -> weaviate.WeaviateClient | None`. Lê `USAR_WEAVIATE` (`auto` padrão, `sim`, `nao`) e `WEAVIATE_URL` (padrão `http://localhost:8080`). Em `auto`, falha de conexão vira aviso no log e devolve `None`. Em `sim`, falha levanta.
  - `criar_indice(nome: str, embeddings: Embeddings) -> Indice`: Weaviate se disponível, senão memória.
- Similaridade é cosseno em ambos. Em memória, vetores normalizados e produto escalar. No Weaviate, `1 - distance` com métrica cosseno, que é o padrão da coleção.

- [ ] **Step 1: Escrever os testes**

`tests/test_indice.py`:

```python
import os

import pytest

from classificador import indice as modulo
from classificador.indice import IndiceMemoria, Resultado, criar_indice
from tests.fakes import EmbeddingsFalsas


def _popular(ind):
    ind.adicionar(
        ["a", "b", "c"],
        ["furto de coisa alheia móvel", "roubo com violência", "prescrição da pretensão punitiva"],
        [{"tema_id": 5159}, {"tema_id": 5160}, {"tema_id": 5188}],
    )


def _contrato(ind):
    _popular(ind)
    assert ind.tamanho() == 3
    resultados = ind.buscar("furto de coisa alheia móvel", k=2)
    assert len(resultados) == 2
    assert isinstance(resultados[0], Resultado)
    assert resultados[0].id == "a"
    assert resultados[0].metadados == {"tema_id": 5159}
    assert resultados[0].similaridade == pytest.approx(1.0, abs=1e-6)
    assert resultados[0].similaridade >= resultados[1].similaridade
    sem_a = ind.buscar("furto de coisa alheia móvel", k=2, excluir=frozenset({"a"}))
    assert [r.id for r in sem_a] == [r.id for r in ind.buscar("furto de coisa alheia móvel", k=3)][1:3]
    assert len(ind.buscar("x", k=10)) == 3


def test_indice_memoria_cumpre_o_contrato():
    _contrato(IndiceMemoria("Teste", EmbeddingsFalsas()))


def test_indice_memoria_vazio_devolve_lista_vazia():
    ind = IndiceMemoria("Teste", EmbeddingsFalsas())
    assert ind.tamanho() == 0
    assert ind.buscar("x", k=3) == []


def test_criar_indice_cai_para_memoria_quando_desligado(monkeypatch):
    monkeypatch.setenv("USAR_WEAVIATE", "nao")
    ind = criar_indice("Teste", EmbeddingsFalsas())
    assert isinstance(ind, IndiceMemoria)


def test_criar_indice_cai_para_memoria_quando_weaviate_nao_responde(monkeypatch):
    monkeypatch.setenv("USAR_WEAVIATE", "auto")
    monkeypatch.setenv("WEAVIATE_URL", "http://localhost:1")
    ind = criar_indice("Teste", EmbeddingsFalsas())
    assert isinstance(ind, IndiceMemoria)


def test_criar_indice_exige_weaviate_quando_obrigatorio(monkeypatch):
    monkeypatch.setenv("USAR_WEAVIATE", "sim")
    monkeypatch.setenv("WEAVIATE_URL", "http://localhost:1")
    with pytest.raises(Exception):
        criar_indice("Teste", EmbeddingsFalsas())


@pytest.mark.skipif(os.environ.get("WEAVIATE_TESTE") != "1", reason="exige Weaviate local; rode com WEAVIATE_TESTE=1")
def test_indice_weaviate_cumpre_o_contrato(monkeypatch):
    monkeypatch.setenv("USAR_WEAVIATE", "sim")
    cliente = modulo.conectar_weaviate()
    ind = modulo.IndiceWeaviate("TesteContrato", EmbeddingsFalsas(), cliente)
    try:
        _contrato(ind)
    finally:
        ind.fechar()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_indice.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.indice`.

- [ ] **Step 3: Implementar `indice.py`**

```python
"""Índice vetorial: Weaviate em Docker, com índice em memória como substituto."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import numpy as np
from langchain_core.embeddings import Embeddings

from classificador.config import ler_env

registro = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resultado:
    id: str
    metadados: dict
    similaridade: float


class Indice(Protocol):
    nome: str

    def adicionar(self, ids: list[str], textos: list[str], metadados: list[dict]) -> None: ...

    def buscar(self, texto: str, k: int, excluir: frozenset[str] = frozenset()) -> list[Resultado]: ...

    def tamanho(self) -> int: ...


def _normalizar(matriz: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return matriz / normas


class IndiceMemoria:
    """Busca por cosseno com NumPy. Serve para testes e para rodar sem Docker."""

    def __init__(self, nome: str, embeddings: Embeddings) -> None:
        self.nome = nome
        self._embeddings = embeddings
        self._ids: list[str] = []
        self._metadados: list[dict] = []
        self._vetores: np.ndarray | None = None

    def adicionar(self, ids: list[str], textos: list[str], metadados: list[dict]) -> None:
        if not ids:
            return
        novos = _normalizar(np.asarray(self._embeddings.embed_documents(textos), dtype=np.float64))
        self._vetores = novos if self._vetores is None else np.vstack([self._vetores, novos])
        self._ids.extend(ids)
        self._metadados.extend(metadados)

    def buscar(self, texto: str, k: int, excluir: frozenset[str] = frozenset()) -> list[Resultado]:
        if self._vetores is None or k <= 0:
            return []
        consulta = _normalizar(np.asarray([self._embeddings.embed_query(texto)], dtype=np.float64))[0]
        similaridades = self._vetores @ consulta
        ordem = np.argsort(-similaridades, kind="stable")
        resultados: list[Resultado] = []
        for posicao in ordem:
            if self._ids[posicao] in excluir:
                continue
            resultados.append(Resultado(self._ids[posicao], dict(self._metadados[posicao]), float(similaridades[posicao])))
            if len(resultados) == k:
                break
        return resultados

    def tamanho(self) -> int:
        return len(self._ids)


class IndiceWeaviate:
    """Coleção no Weaviate com vetores fornecidos por nós (sem vetorizador do servidor)."""

    def __init__(self, nome: str, embeddings: Embeddings, cliente) -> None:
        from weaviate.classes.config import Configure, DataType, Property

        self.nome = nome
        self._embeddings = embeddings
        self._cliente = cliente
        if cliente.collections.exists(nome):
            cliente.collections.delete(nome)
        propriedades = [
            Property(name="id_externo", data_type=DataType.TEXT),
            Property(name="metadados_json", data_type=DataType.TEXT),
        ]
        if hasattr(Configure, "Vectors"):
            self._colecao = cliente.collections.create(
                name=nome, properties=propriedades, vector_config=Configure.Vectors.self_provided()
            )
        else:
            self._colecao = cliente.collections.create(
                name=nome, properties=propriedades, vectorizer_config=Configure.Vectorizer.none()
            )

    def adicionar(self, ids: list[str], textos: list[str], metadados: list[dict]) -> None:
        if not ids:
            return
        vetores = self._embeddings.embed_documents(textos)
        with self._colecao.batch.dynamic() as lote:
            for id_externo, meta, vetor in zip(ids, metadados, vetores):
                lote.add_object(
                    properties={"id_externo": id_externo, "metadados_json": json.dumps(meta, ensure_ascii=False)},
                    vector=vetor,
                )
        falhas = self._colecao.batch.failed_objects
        if falhas:
            raise RuntimeError(f"Weaviate recusou {len(falhas)} objeto(s) na coleção {self.nome}: {falhas[0]}")

    def buscar(self, texto: str, k: int, excluir: frozenset[str] = frozenset()) -> list[Resultado]:
        from weaviate.classes.query import MetadataQuery

        if k <= 0 or self.tamanho() == 0:
            return []
        vetor = self._embeddings.embed_query(texto)
        resposta = self._colecao.query.near_vector(
            near_vector=vetor,
            limit=k + len(excluir),
            return_metadata=MetadataQuery(distance=True),
            return_properties=["id_externo", "metadados_json"],
        )
        resultados: list[Resultado] = []
        for objeto in resposta.objects:
            id_externo = str(objeto.properties["id_externo"])
            if id_externo in excluir:
                continue
            metadados = json.loads(objeto.properties["metadados_json"])
            resultados.append(Resultado(id_externo, metadados, 1.0 - float(objeto.metadata.distance)))
            if len(resultados) == k:
                break
        return resultados

    def tamanho(self) -> int:
        return int(self._colecao.aggregate.over_all(total_count=True).total_count or 0)

    def fechar(self) -> None:
        self._cliente.close()


def conectar_weaviate():
    modo = (ler_env("USAR_WEAVIATE", "auto") or "auto").lower()
    if modo == "nao":
        return None
    url = urlparse(ler_env("WEAVIATE_URL", "http://localhost:8080") or "http://localhost:8080")
    try:
        import weaviate
        from weaviate.classes.init import AdditionalConfig, Timeout

        cliente = weaviate.connect_to_local(
            host=url.hostname or "localhost",
            port=url.port or 8080,
            grpc_port=50051,
            additional_config=AdditionalConfig(timeout=Timeout(init=5, query=30, insert=120)),
        )
        if not cliente.is_ready():
            cliente.close()
            raise ConnectionError("Weaviate respondeu mas não está pronto")
        return cliente
    except Exception as erro:
        if modo == "sim":
            raise
        registro.warning("Weaviate indisponível (%s); usando índice em memória.", erro)
        return None


def criar_indice(nome: str, embeddings: Embeddings) -> Indice:
    cliente = conectar_weaviate()
    if cliente is None:
        return IndiceMemoria(nome, embeddings)
    return IndiceWeaviate(nome, embeddings, cliente)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_indice.py -v`
Expected: 5 PASS, 1 SKIPPED. O teste de fallback por conexão recusada pode levar alguns segundos.

- [ ] **Step 5: Verificar contra o Weaviate real**

Run: `docker compose up -d` e depois `WEAVIATE_TESTE=1 uv run pytest tests/test_indice.py -v -k weaviate`. No PowerShell: `$env:WEAVIATE_TESTE="1"; uv run pytest tests/test_indice.py -v -k weaviate`.
Expected: o teste de contrato do Weaviate PASS. Se o Docker Desktop não estiver rodando, abrir o Docker Desktop antes. Registrar no commit se o teste rodou.

- [ ] **Step 6: Commit**

```bash
git add src/classificador/indice.py tests/test_indice.py
git commit -m "Índice vetorial com Weaviate e substituto em memória por cosseno"
```

---

### Task 6: Candidatos por questão em duas passadas

**Files:**
- Create: `src/classificador/candidatos.py`, `tests/test_candidatos.py`

**Interfaces:**
- Consumes: `ArvoreTemas`, `Indice`, `criar_indice`, `carregar_questoes`, `carregar_corpus`, `escrever_jsonl`.
- Produces:
  - `@dataclass(frozen=True) Candidato(tema_id: int, origem: str, similaridade: float)`; `origem` em `{"tema", "corpus", "pai"}`.
  - Constantes `K_TEMAS = 8`, `K_CORPUS = 10`, `TETO = 12`.
  - `montar_indice_temas(arvore, embeddings, criar=criar_indice) -> Indice`: um documento por tema publicável, `id` é `str(tema_id)`, metadados `{"tema_id": int}`.
  - `montar_indice_corpus(corpus_df, arvore, embeddings, criar=criar_indice) -> Indice`: `id` é o id do corpus, metadados `{"tema_id": canônico, "id": id}`.
  - `buscar_candidatos(texto, indice_temas, arvore, indice_corpus=None, excluir_corpus=frozenset(), k_temas=K_TEMAS, k_corpus=K_CORPUS, teto=TETO) -> list[Candidato]`, ordenado por similaridade decrescente e, em empate, nível crescente, para o pai vir antes do filho.
  - `candidatos_para_dict(lista) -> list[dict]` e `candidatos_de_dict(lista) -> list[Candidato]`.
  - `rodar_candidatos(alvo: str, passada: int, arvore, embeddings, pasta_saida=CAMINHOS.intermediarios, criar=criar_indice) -> Path`. Grava `candidatos_<alvo>_p<passada>.jsonl`. Quando `alvo == "questoes"` e `passada == 1`, grava também `temas_alvo_corpus.json` com a lista ordenada dos temas candidatos mais seus pais, que define o que os agentes vão coletar.
  - `main()` com `--alvo {questoes,corpus}` e `--passada {1,2}`.

- [ ] **Step 1: Escrever os testes**

`tests/test_candidatos.py`:

```python
import json

import pandas as pd
import pytest

from classificador import candidatos as modulo
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato, buscar_candidatos, montar_indice_corpus, montar_indice_temas
from classificador.dados import ler_jsonl
from classificador.indice import IndiceMemoria
from tests.fakes import EmbeddingsFalsas


def criar_memoria(nome, embeddings):
    return IndiceMemoria(nome, embeddings)


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


@pytest.fixture(scope="module")
def indice_temas(arvore):
    return montar_indice_temas(arvore, EmbeddingsFalsas(), criar=criar_memoria)


def test_indice_de_temas_tem_um_documento_por_tema_publicavel(arvore, indice_temas):
    assert indice_temas.tamanho() == len(arvore.candidatos_possiveis())


def test_candidatos_respeitam_teto_pais_e_ordem(arvore, indice_temas):
    lista = buscar_candidatos("qualquer texto de questão", indice_temas, arvore)
    assert 0 < len(lista) <= modulo.TETO
    ids = [c.tema_id for c in lista]
    assert len(ids) == len(set(ids))
    for c in lista:
        assert arvore.publicavel(c.tema_id)
        if arvore.nivel(c.tema_id) == 2:
            pai = arvore.pai(c.tema_id)
            assert pai in ids
            assert ids.index(pai) < ids.index(c.tema_id)
    similaridades = [c.similaridade for c in lista]
    assert similaridades == sorted(similaridades, reverse=True)


def test_vizinho_do_corpus_vira_candidato_com_origem_corpus(arvore, indice_temas):
    corpus = pd.DataFrame([{
        "id": "C0001", "tema_id": 6724, "texto": "texto identico ao da consulta",
    }])
    indice_corpus = montar_indice_corpus(corpus, arvore, EmbeddingsFalsas(), criar=criar_memoria)
    # k_temas=0 isola a fonte corpus: com embeddings falsos, o tema poderia vir por acaso do índice de temas.
    lista = buscar_candidatos("texto identico ao da consulta", indice_temas, arvore, indice_corpus, k_temas=0)
    por_id = {c.tema_id: c for c in lista}
    assert 4704 in por_id
    assert por_id[4704].origem == "corpus"
    assert por_id[4704].similaridade == pytest.approx(1.0, abs=1e-6)


def test_excluir_corpus_tira_a_propria_questao(arvore, indice_temas):
    corpus = pd.DataFrame([{"id": "C0001", "tema_id": 5527, "texto": "texto identico ao da consulta"}])
    indice_corpus = montar_indice_corpus(corpus, arvore, EmbeddingsFalsas(), criar=criar_memoria)
    lista = buscar_candidatos(
        "texto identico ao da consulta", indice_temas, arvore, indice_corpus, excluir_corpus=frozenset({"C0001"})
    )
    assert all(c.origem != "corpus" for c in lista)


def test_ida_e_volta_para_dict():
    lista = [Candidato(5527, "tema", 0.5)]
    assert modulo.candidatos_de_dict(modulo.candidatos_para_dict(lista)) == lista


def test_rodar_candidatos_passada_1_grava_jsonl_e_temas_alvo(arvore, tmp_path):
    saida = modulo.rodar_candidatos("questoes", 1, arvore, EmbeddingsFalsas(), pasta_saida=tmp_path, criar=criar_memoria)
    linhas = ler_jsonl(saida)
    assert len(linhas) == 359
    assert set(linhas[0]) == {"id", "candidatos"}
    alvo = json.loads((tmp_path / "temas_alvo_corpus.json").read_text(encoding="utf-8"))
    assert alvo == sorted(alvo)
    assert all(arvore.publicavel(t) for t in alvo)
    for linha in linhas:
        for c in linha["candidatos"]:
            assert c["tema_id"] in alvo
            if arvore.nivel(c["tema_id"]) == 2:
                assert arvore.pai(c["tema_id"]) in alvo
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_candidatos.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.candidatos`.

- [ ] **Step 3: Implementar `candidatos.py`**

```python
"""Temas candidatos por questão: similaridade com temas, vizinhos do corpus e pais."""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from langchain_core.embeddings import Embeddings

from classificador.arvore import ArvoreTemas
from classificador.config import CAMINHOS
from classificador.dados import carregar_corpus, carregar_questoes, escrever_jsonl
from classificador.embeddings import criar_embeddings
from classificador.indice import Indice, criar_indice

registro = logging.getLogger(__name__)

K_TEMAS = 8
K_CORPUS = 10
TETO = 12


@dataclass(frozen=True)
class Candidato:
    tema_id: int
    origem: str
    similaridade: float


def montar_indice_temas(arvore: ArvoreTemas, embeddings: Embeddings, criar=criar_indice) -> Indice:
    ids = arvore.candidatos_possiveis()
    indice = criar("Tema", embeddings)
    indice.adicionar([str(t) for t in ids], [arvore.documento(t) for t in ids], [{"tema_id": t} for t in ids])
    return indice


def montar_indice_corpus(corpus: pd.DataFrame, arvore: ArvoreTemas, embeddings: Embeddings, criar=criar_indice) -> Indice:
    indice = criar("CorpusQuestao", embeddings)
    if len(corpus) == 0:
        return indice
    ids = [str(i) for i in corpus["id"]]
    metadados = [{"tema_id": arvore.canonico(int(t)), "id": str(i)} for t, i in zip(corpus["tema_id"], corpus["id"])]
    indice.adicionar(ids, list(corpus["texto"]), metadados)
    return indice


def _registrar(acumulado: dict[int, Candidato], tema_id: int, origem: str, similaridade: float) -> None:
    atual = acumulado.get(tema_id)
    if atual is None:
        acumulado[tema_id] = Candidato(tema_id, origem, similaridade)
    elif similaridade > atual.similaridade:
        acumulado[tema_id] = Candidato(tema_id, atual.origem, similaridade)


def buscar_candidatos(
    texto: str,
    indice_temas: Indice,
    arvore: ArvoreTemas,
    indice_corpus: Indice | None = None,
    excluir_corpus: frozenset[str] = frozenset(),
    k_temas: int = K_TEMAS,
    k_corpus: int = K_CORPUS,
    teto: int = TETO,
) -> list[Candidato]:
    acumulado: dict[int, Candidato] = {}
    for resultado in indice_temas.buscar(texto, k_temas):
        _registrar(acumulado, int(resultado.metadados["tema_id"]), "tema", resultado.similaridade)
    if indice_corpus is not None and indice_corpus.tamanho() > 0:
        for resultado in indice_corpus.buscar(texto, k_corpus, excluir=excluir_corpus):
            tema_id = arvore.canonico(int(resultado.metadados["tema_id"]))
            if arvore.publicavel(tema_id):
                _registrar(acumulado, tema_id, "corpus", resultado.similaridade)
    for candidato in list(acumulado.values()):
        if arvore.nivel(candidato.tema_id) == 2:
            pai = arvore.pai(candidato.tema_id)
            if pai is not None and arvore.publicavel(pai):
                _registrar(acumulado, pai, "pai", candidato.similaridade)
    ordenados = sorted(acumulado.values(), key=lambda c: (-c.similaridade, arvore.nivel(c.tema_id)))
    return ordenados[:teto]


def candidatos_para_dict(lista: list[Candidato]) -> list[dict]:
    return [asdict(c) for c in lista]


def candidatos_de_dict(lista: list[dict]) -> list[Candidato]:
    return [Candidato(int(c["tema_id"]), str(c["origem"]), float(c["similaridade"])) for c in lista]


def rodar_candidatos(
    alvo: str,
    passada: int,
    arvore: ArvoreTemas,
    embeddings: Embeddings,
    pasta_saida: Path = CAMINHOS.intermediarios,
    criar=criar_indice,
) -> Path:
    if alvo not in {"questoes", "corpus"}:
        raise ValueError("alvo deve ser 'questoes' ou 'corpus'")
    if alvo == "corpus" and passada != 2:
        raise ValueError("o corpus só roda na passada 2")
    indice_temas = montar_indice_temas(arvore, embeddings, criar)
    indice_corpus: Indice | None = None
    if passada == 2:
        if CAMINHOS.corpus.exists():
            corpus = carregar_corpus()
        else:
            registro.warning("corpus ausente em %s; passada 2 roda só com os temas", CAMINHOS.corpus)
            corpus = pd.DataFrame(columns=["id", "tema_id", "texto"])
        indice_corpus = montar_indice_corpus(corpus, arvore, embeddings, criar)
    if alvo == "corpus" and not CAMINHOS.corpus.exists():
        raise FileNotFoundError(f"corpus ausente em {CAMINHOS.corpus}")
    df = carregar_questoes() if alvo == "questoes" else carregar_corpus()
    linhas: list[dict] = []
    for id_, texto in zip(df["id"], df["texto"]):
        excluir = frozenset({str(id_)}) if alvo == "corpus" else frozenset()
        lista = buscar_candidatos(texto, indice_temas, arvore, indice_corpus, excluir_corpus=excluir)
        linhas.append({"id": str(id_), "candidatos": candidatos_para_dict(lista)})
    saida = pasta_saida / f"candidatos_{alvo}_p{passada}.jsonl"
    escrever_jsonl(saida, linhas)
    registro.info("gravado %s com %d linhas", saida, len(linhas))
    if alvo == "questoes" and passada == 1:
        alvo_corpus: set[int] = set()
        for linha in linhas:
            for c in linha["candidatos"]:
                alvo_corpus.add(int(c["tema_id"]))
                if arvore.nivel(int(c["tema_id"])) == 2:
                    pai = arvore.pai(int(c["tema_id"]))
                    if pai is not None and arvore.publicavel(pai):
                        alvo_corpus.add(pai)
        caminho_alvo = pasta_saida / "temas_alvo_corpus.json"
        caminho_alvo.write_text(json.dumps(sorted(alvo_corpus)), encoding="utf-8")
        registro.info("%d temas alvo para o corpus em %s", len(alvo_corpus), caminho_alvo)
    return saida


def main(argumentos: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Gera os temas candidatos por questão.")
    parser.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")
    parser.add_argument("--passada", type=int, choices=[1, 2], default=1)
    args = parser.parse_args(argumentos)
    rodar_candidatos(args.alvo, args.passada, ArvoreTemas.carregar(), criar_embeddings())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_candidatos.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/classificador/candidatos.py tests/test_candidatos.py
git commit -m "Candidatos por questão com temas, vizinhos do corpus e pais, em duas passadas"
```

---

### Task 7: Planilha da âncora manual

**Files:**
- Create: `src/classificador/ancora.py`, `tests/test_ancora.py`

**Interfaces:**
- Consumes: `carregar_questoes`, `ler_jsonl`, `ArvoreTemas`, `config.SEMENTE`, `CAMINHOS.ancora_planilha`, `CAMINHOS.ancora_manual`.
- Produces:
  - `N_ANCORA = 40`
  - `sortear_ancora(questoes: pd.DataFrame, n=N_ANCORA, semente=SEMENTE) -> pd.DataFrame`: amostra estratificada por `disciplina_origem` com alocação proporcional arredondada; a diferença de arredondamento vai para o maior grupo. Ordenada por `id`.
  - `formatar_candidatos_para_planilha(candidatos: list[dict], arvore) -> str`: uma linha por candidato, `"<id> | <caminho> | <descrição até 200 caracteres>"`.
  - `gerar_planilha_ancora(questoes, candidatos_por_id: dict[str, list[dict]], arvore, n=N_ANCORA, semente=SEMENTE) -> pd.DataFrame` com colunas `id, disciplina_origem, texto, candidatos, tema_id_gilson, observacao`.
  - `rodar_ancora(caminho_candidatos=CAMINHOS.intermediarios / "candidatos_questoes_p1.jsonl", saida=CAMINHOS.ancora_planilha) -> Path`
  - `carregar_ancora_manual(arvore, caminho=CAMINHOS.ancora_manual) -> pd.DataFrame` com colunas `id, tema_id`; levanta `ValueError` se algum `tema_id` não é publicável.

- [ ] **Step 1: Escrever os testes**

`tests/test_ancora.py`:

```python
import pandas as pd
import pytest

from classificador import ancora
from classificador.arvore import ArvoreTemas
from classificador.dados import carregar_questoes


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


@pytest.fixture(scope="module")
def questoes():
    return carregar_questoes()


def test_sorteio_tem_40_e_e_deterministico(questoes):
    a = ancora.sortear_ancora(questoes)
    b = ancora.sortear_ancora(questoes)
    assert len(a) == 40
    assert list(a["id"]) == list(b["id"])
    assert a["id"].is_unique
    assert list(a["id"]) == sorted(a["id"])


def test_sorteio_e_proporcional_por_disciplina(questoes):
    a = ancora.sortear_ancora(questoes)
    contagem = a["disciplina_origem"].value_counts()
    assert 14 <= contagem["Processo Penal"] <= 16
    assert 13 <= contagem["Direito Penal"] <= 15
    assert contagem.sum() == 40


def test_planilha_tem_colunas_e_candidatos_formatados(questoes, arvore):
    candidatos = {i: [{"tema_id": 5527, "origem": "tema", "similaridade": 0.5}] for i in questoes["id"]}
    planilha = ancora.gerar_planilha_ancora(questoes, candidatos, arvore)
    assert list(planilha.columns) == ["id", "disciplina_origem", "texto", "candidatos", "tema_id_gilson", "observacao"]
    assert len(planilha) == 40
    assert planilha.loc[0, "candidatos"].startswith("5527 | Processo Penal > Procedimento do Tribunal do Júri >")
    assert (planilha["tema_id_gilson"] == "").all()


def test_carregar_ancora_manual_valida_temas(arvore, tmp_path):
    caminho = tmp_path / "ancora_manual.csv"
    pd.DataFrame({"id": ["Q0001"], "tema_id": [5527]}).to_csv(caminho, index=False)
    df = ancora.carregar_ancora_manual(arvore, caminho)
    assert list(df["id"]) == ["Q0001"]
    pd.DataFrame({"id": ["Q0001"], "tema_id": [6724]}).to_csv(caminho, index=False)
    with pytest.raises(ValueError, match="6724"):
        ancora.carregar_ancora_manual(arvore, caminho)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_ancora.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.ancora`.

- [ ] **Step 3: Implementar `ancora.py`**

```python
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
COLUNAS = ["id", "disciplina_origem", "texto", "candidatos", "tema_id_gilson", "observacao"]


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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_ancora.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/classificador/ancora.py tests/test_ancora.py
git commit -m "Planilha da âncora manual estratificada por disciplina de origem"
```

---

### Task 8: Votos dos modelos de linguagem

**Files:**
- Create: `src/classificador/llm.py`, `src/classificador/prompts/classificar.md`, `tests/test_llm.py`

**Interfaces:**
- Consumes: `Candidato`, `candidatos_de_dict`, `ArvoreTemas`, `carregar_questoes`, `carregar_corpus`, `ler_jsonl`, `escrever_jsonl`, `config.ler_env`, `config.ChaveAusenteError`, `CAMINHOS.prompts`, `CAMINHOS.cache`.
- Produces:
  - `class VotoModelo(pydantic.BaseModel)`: `tema_central_id: int | None`, `extras_ids: list[int]`, `disciplina: Literal["Penal", "Processo Penal", "Legislação Especial", "Criminologia", "Outra"]`, `confianca: float` em `[0, 1]`, `justificativa: str`.
  - `class VotoInvalidoError(ValueError)`.
  - `Invocador = Callable[[str], VotoModelo]`.
  - `carregar_prompt(caminho=CAMINHOS.prompts / "classificar.md") -> str`, `formatar_candidatos(candidatos: list[Candidato], arvore) -> str`, `montar_prompt(template, texto_questao, candidatos, arvore) -> str`. Marcadores no template: `{{QUESTAO}}` e `{{CANDIDATOS}}`.
  - `class ClassificadorLLM(nome, modelo, invocador: Invocador | None, pasta_cache, template, tentativas=3, espera_base=2.0, dormir=time.sleep)` com `classificar(texto_questao, candidatos, arvore) -> VotoModelo | None` e `validar(voto, candidatos, arvore) -> VotoModelo`.
  - `criar_invocador(provedor: str, modelo: str) -> Invocador`.
  - `criar_classificadores(pasta_cache=CAMINHOS.cache) -> tuple[ClassificadorLLM, ClassificadorLLM]`, ordem `(openai, anthropic)`. Modelos de `MODELO_OPENAI` (padrão `gpt-5`) e `MODELO_ANTHROPIC` (padrão `claude-sonnet-5-5`).
  - `rodar_votos(alvo, arvore, caminho_candidatos, classificadores, pasta_saida=CAMINHOS.intermediarios, limite=None) -> Path`. Grava `votos_llm_<alvo>.jsonl`.
  - `verificar_provedores() -> dict[str, str]`: uma chamada mínima por provedor; devolve `"ok"` ou a mensagem de erro.
  - `main()` com `--alvo`, `--passada` (padrão 2), `--limite`, `--verificar`.
- Comportamento: cache por SHA-256 de `modelo + prompt + schema`; só votos válidos vão para o cache. Erro de API: até `tentativas` chamadas com espera `espera_base * 2**i`; esgotadas, devolve `None`. Voto com `tema_central_id` fora dos candidatos: uma única nova chamada com aviso no fim do prompt; se persistir, `None`. `extras_ids` fora dos candidatos ou iguais ao central são descartados em silêncio. Ids são canonicalizados antes da validação.

- [ ] **Step 1: Escrever o prompt**

`src/classificador/prompts/classificar.md`:

```markdown
Você é um especialista em Direito Penal, Processo Penal, Legislação Penal Especial e Criminologia. Sua tarefa é classificar uma questão de concurso público num tema de uma plataforma de estudos.

Como a plataforma usa a classificação: o aluno escolhe um tema e resolve as questões ligadas a ele. Se a questão estiver no tema errado, o aluno estuda a matéria errada. Publicar errado custa caro. É melhor declarar confiança baixa do que fingir certeza.

Como a classificação é avaliada: conta como certo o tema que a equipe de especialistas atribuiu, ou um nó pai ou filho dele na árvore. Colocar num subtema irmão conta como erro.

Regras de escolha:
1. Escolha somente entre os candidatos listados abaixo, pelo id. Se nenhum serve, devolva tema_central_id nulo e explique na justificativa qual seria o assunto.
2. Prefira o subtema, que é o nível mais específico, quando a questão é claramente sobre ele.
3. Prefira o tema pai quando a questão cobre vários subtemas do mesmo ramo ao mesmo tempo.
4. Temas introdutórios ou gerais, como conceito, fontes, princípios, sistemas, classificação ou noções gerais, só quando a questão é sobre o conceito ou princípio em si. Nunca os escolha por serem os mais genéricos.
5. Leia as alternativas. Muitas vezes o enunciado é genérico e o assunto real está nelas.
6. A questão pode ser de outra disciplina, como Tributário, Civil, Constitucional, Ambiental ou Administrativo. Nesse caso devolva disciplina "Outra" e tema_central_id nulo.
7. Em extras_ids, liste outros candidatos que a questão também cobre de forma relevante. Pode ficar vazio.
8. A confiança é a sua estimativa honesta da chance de o tema central estar certo pela régua acima. Use valores baixos quando houver dois candidatos igualmente plausíveis.

Questão:
{{QUESTAO}}

Candidatos:
{{CANDIDATOS}}

Responda no formato estruturado pedido, com justificativa de no máximo duas frases.
```

- [ ] **Step 2: Escrever os testes**

`tests/test_llm.py`:

```python
import json

import pytest

from classificador import llm
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato
from classificador.config import ChaveAusenteError
from classificador.llm import ClassificadorLLM, VotoModelo

CANDIDATOS = [Candidato(5524, "tema", 0.7), Candidato(5527, "tema", 0.6), Candidato(5159, "tema", 0.3)]
TEMPLATE = "Q:\n{{QUESTAO}}\nC:\n{{CANDIDATOS}}"


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def voto(tema, extras=(), confianca=0.9, disciplina="Processo Penal"):
    return VotoModelo(tema_central_id=tema, extras_ids=list(extras), disciplina=disciplina, confianca=confianca, justificativa="x")


class InvocadorFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def classificador(invocador, tmp_path, **kw):
    esperas = []
    clf = ClassificadorLLM("falso", "modelo-x", invocador, tmp_path, TEMPLATE, dormir=esperas.append, **kw)
    return clf, esperas


def test_montar_prompt_substitui_marcadores(arvore):
    prompt = llm.montar_prompt(TEMPLATE, "enunciado", CANDIDATOS[:1], arvore)
    assert "Q:\nenunciado" in prompt
    assert "- id 5524: Processo Penal > Procedimento do Tribunal do Júri" in prompt
    assert "{{" not in prompt


def test_segunda_chamada_vem_do_cache(arvore, tmp_path):
    inv = InvocadorFalso([voto(5527)])
    clf, _ = classificador(inv, tmp_path)
    primeiro = clf.classificar("t", CANDIDATOS, arvore)
    segundo = clf.classificar("t", CANDIDATOS, arvore)
    assert primeiro == segundo
    assert len(inv.prompts) == 1


def test_tema_fora_dos_candidatos_tenta_uma_vez_e_devolve_none(arvore, tmp_path):
    inv = InvocadorFalso([voto(9999), voto(9999)])
    clf, _ = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore) is None
    assert len(inv.prompts) == 2
    assert "9999" in inv.prompts[1]
    assert not list((tmp_path / "llm").rglob("*.json"))


def test_tema_invalido_depois_valido(arvore, tmp_path):
    inv = InvocadorFalso([voto(9999), voto(5527)])
    clf, _ = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5527


def test_extras_sao_filtrados_e_central_canonicalizado(arvore, tmp_path):
    inv = InvocadorFalso([voto(5527, extras=[5527, 5524, 4242])])
    clf, _ = classificador(inv, tmp_path)
    resultado = clf.classificar("t", CANDIDATOS, arvore)
    assert resultado.extras_ids == [5524]


def test_erro_de_api_retenta_com_espera_exponencial(arvore, tmp_path):
    inv = InvocadorFalso([RuntimeError("503"), RuntimeError("503"), voto(5524)])
    clf, esperas = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5524
    assert esperas == [2.0, 4.0]


def test_erro_de_api_persistente_devolve_none(arvore, tmp_path):
    inv = InvocadorFalso([RuntimeError("x")] * 3)
    clf, _ = classificador(inv, tmp_path)
    assert clf.classificar("t", CANDIDATOS, arvore) is None
    assert len(inv.prompts) == 3


def test_sem_invocador_e_sem_cache_levanta_chave_ausente(arvore, tmp_path):
    clf, _ = classificador(None, tmp_path)
    with pytest.raises(ChaveAusenteError, match="falso"):
        clf.classificar("t", CANDIDATOS, arvore)


def test_cache_corrompido_e_regravado(arvore, tmp_path):
    inv = InvocadorFalso([voto(5527), voto(5524)])
    clf, _ = classificador(inv, tmp_path)
    clf.classificar("t", CANDIDATOS, arvore)
    arquivo = next((tmp_path / "llm").rglob("*.json"))
    arquivo.write_text("{quebrado", encoding="utf-8")
    assert clf.classificar("t", CANDIDATOS, arvore).tema_central_id == 5524
    assert json.loads(arquivo.read_text(encoding="utf-8"))["tema_central_id"] == 5524


def test_voto_none_e_disciplina_outra_sao_validos(arvore, tmp_path):
    inv = InvocadorFalso([voto(None, disciplina="Outra", confianca=0.2)])
    clf, _ = classificador(inv, tmp_path)
    resultado = clf.classificar("t", CANDIDATOS, arvore)
    assert resultado.tema_central_id is None
    assert resultado.disciplina == "Outra"


def test_rodar_votos_grava_jsonl(arvore, tmp_path):
    from classificador.dados import escrever_jsonl, ler_jsonl

    candidatos = tmp_path / "cand.jsonl"
    escrever_jsonl(candidatos, [
        {"id": "Q0001", "candidatos": [{"tema_id": 5524, "origem": "tema", "similaridade": 0.5}]},
        {"id": "Q0002", "candidatos": [{"tema_id": 5524, "origem": "tema", "similaridade": 0.5}]},
    ])
    a, _ = classificador(InvocadorFalso([voto(5524), voto(5524)]), tmp_path / "a")
    b, _ = classificador(InvocadorFalso([voto(5524), RuntimeError("x"), RuntimeError("x"), RuntimeError("x")]), tmp_path / "b")
    saida = llm.rodar_votos("questoes", arvore, candidatos, (a, b), pasta_saida=tmp_path, limite=2)
    linhas = ler_jsonl(saida)
    assert [l["id"] for l in linhas] == ["Q0001", "Q0002"]
    assert linhas[0]["openai"]["tema_central_id"] == 5524
    assert linhas[1]["anthropic"] is None
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.llm`.

- [ ] **Step 4: Implementar `llm.py`**

```python
"""Votos dos modelos de linguagem: prompt, schema estruturado, cache e retentativas."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato, candidatos_de_dict
from classificador.config import CAMINHOS, ChaveAusenteError, ler_env
from classificador.dados import carregar_corpus, carregar_questoes, escrever_jsonl, ler_jsonl

registro = logging.getLogger(__name__)

Disciplina = Literal["Penal", "Processo Penal", "Legislação Especial", "Criminologia", "Outra"]


class VotoModelo(BaseModel):
    tema_central_id: int | None = Field(description="id do candidato escolhido; nulo se nenhum serve")
    extras_ids: list[int] = Field(default_factory=list, description="outros candidatos que a questão também cobre")
    disciplina: Disciplina = Field(description="disciplina da questão; Outra se não é nenhuma das quatro")
    confianca: float = Field(ge=0, le=1, description="chance de o tema central estar certo")
    justificativa: str = Field(description="no máximo duas frases")


class VotoInvalidoError(ValueError):
    """O modelo escolheu um tema que não estava entre os candidatos."""


Invocador = Callable[[str], VotoModelo]

AVISO_RETENTATIVA = (
    "\n\nATENÇÃO: sua resposta anterior escolheu o id {id}, que NÃO está na lista de candidatos. "
    "Escolha somente um id da lista ou devolva tema_central_id nulo."
)


def carregar_prompt(caminho: Path = CAMINHOS.prompts / "classificar.md") -> str:
    return caminho.read_text(encoding="utf-8")


def formatar_candidatos(candidatos: list[Candidato], arvore: ArvoreTemas) -> str:
    linhas = []
    for c in candidatos:
        documento = arvore.documento(c.tema_id).split("\n", 1)
        linhas.append(f"- id {c.tema_id}: {arvore.caminho(c.tema_id)}")
        if len(documento) > 1 and documento[1].strip():
            linhas.append(f"  {documento[1].strip()}")
    return "\n".join(linhas)


def montar_prompt(template: str, texto_questao: str, candidatos: list[Candidato], arvore: ArvoreTemas) -> str:
    return template.replace("{{QUESTAO}}", texto_questao).replace("{{CANDIDATOS}}", formatar_candidatos(candidatos, arvore))


class ClassificadorLLM:
    def __init__(
        self,
        nome: str,
        modelo: str,
        invocador: Invocador | None,
        pasta_cache: Path,
        template: str,
        tentativas: int = 3,
        espera_base: float = 2.0,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.nome = nome
        self.modelo = modelo
        self.invocador = invocador
        self.pasta = pasta_cache / "llm" / nome / modelo
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.template = template
        self.tentativas = tentativas
        self.espera_base = espera_base
        self.dormir = dormir
        self.chamadas = 0
        self.acertos_cache = 0

    def _arquivo(self, prompt: str) -> Path:
        schema = json.dumps(VotoModelo.model_json_schema(), sort_keys=True)
        chave = hashlib.sha256(f"{self.modelo}\n{prompt}\n{schema}".encode("utf-8")).hexdigest()
        return self.pasta / f"{chave}.json"

    def _ler_cache(self, prompt: str) -> VotoModelo | None:
        arquivo = self._arquivo(prompt)
        if not arquivo.exists():
            return None
        try:
            return VotoModelo.model_validate_json(arquivo.read_text(encoding="utf-8"))
        except Exception:
            arquivo.unlink()
            return None

    def _gravar_cache(self, prompt: str, voto: VotoModelo) -> None:
        self._arquivo(prompt).write_text(voto.model_dump_json(), encoding="utf-8")

    def validar(self, voto: VotoModelo, candidatos: list[Candidato], arvore: ArvoreTemas) -> VotoModelo:
        permitidos = {c.tema_id for c in candidatos}
        central = None if voto.tema_central_id is None else arvore.canonico(voto.tema_central_id)
        if central is not None and central not in permitidos:
            raise VotoInvalidoError(str(voto.tema_central_id))
        extras: list[int] = []
        for extra in voto.extras_ids:
            if not arvore.existe(extra):
                continue
            canonico = arvore.canonico(extra)
            if canonico in permitidos and canonico != central and canonico not in extras:
                extras.append(canonico)
        return voto.model_copy(update={"tema_central_id": central, "extras_ids": extras})

    def _invocar_com_retentativas(self, prompt: str) -> VotoModelo | None:
        assert self.invocador is not None
        for tentativa in range(self.tentativas):
            try:
                self.chamadas += 1
                return self.invocador(prompt)
            except VotoInvalidoError:
                raise
            except Exception as erro:
                registro.warning("%s: erro na chamada (%s), tentativa %d/%d", self.nome, erro, tentativa + 1, self.tentativas)
                if tentativa + 1 < self.tentativas:
                    self.dormir(self.espera_base * (2 ** tentativa))
        return None

    def classificar(self, texto_questao: str, candidatos: list[Candidato], arvore: ArvoreTemas) -> VotoModelo | None:
        prompt = montar_prompt(self.template, texto_questao, candidatos, arvore)
        em_cache = self._ler_cache(prompt)
        if em_cache is not None:
            try:
                self.acertos_cache += 1
                return self.validar(em_cache, candidatos, arvore)
            except VotoInvalidoError:
                self._arquivo(prompt).unlink()
        if self.invocador is None:
            raise ChaveAusenteError(
                f"classificador '{self.nome}' sem chave de API e sem cache para esta questão. "
                "Defina a chave no .env ou use o cache commitado."
            )
        prompt_atual = prompt
        for rodada in range(2):
            bruto = self._invocar_com_retentativas(prompt_atual)
            if bruto is None:
                return None
            try:
                voto = self.validar(bruto, candidatos, arvore)
            except VotoInvalidoError as erro:
                registro.warning("%s: tema %s fora dos candidatos (rodada %d)", self.nome, erro, rodada + 1)
                prompt_atual = prompt + AVISO_RETENTATIVA.format(id=erro)
                continue
            self._gravar_cache(prompt, voto)
            return voto
        return None


def criar_invocador(provedor: str, modelo: str) -> Invocador:
    if provedor == "openai":
        from langchain_openai import ChatOpenAI

        if modelo.startswith("gpt-5") or modelo.startswith("o"):
            base = ChatOpenAI(model=modelo, reasoning_effort="low")
        else:
            base = ChatOpenAI(model=modelo, temperature=0)
    elif provedor == "anthropic":
        from langchain_anthropic import ChatAnthropic

        base = ChatAnthropic(model=modelo, temperature=0, max_tokens=1024)
    else:
        raise ValueError(f"provedor desconhecido: {provedor}")
    estruturado = base.with_structured_output(VotoModelo)

    def invocar(prompt: str) -> VotoModelo:
        resultado = estruturado.invoke(prompt)
        if not isinstance(resultado, VotoModelo):
            raise RuntimeError(f"{provedor} devolveu algo que não é VotoModelo: {type(resultado)}")
        return resultado

    return invocar


def criar_classificadores(pasta_cache: Path = CAMINHOS.cache) -> tuple[ClassificadorLLM, ClassificadorLLM]:
    template = carregar_prompt()
    modelo_openai = ler_env("MODELO_OPENAI", "gpt-5") or "gpt-5"
    modelo_anthropic = ler_env("MODELO_ANTHROPIC", "claude-sonnet-5-5") or "claude-sonnet-5-5"
    inv_openai = criar_invocador("openai", modelo_openai) if ler_env("OPENAI_API_KEY") else None
    inv_anthropic = criar_invocador("anthropic", modelo_anthropic) if ler_env("ANTHROPIC_API_KEY") else None
    return (
        ClassificadorLLM("openai", modelo_openai, inv_openai, pasta_cache, template),
        ClassificadorLLM("anthropic", modelo_anthropic, inv_anthropic, pasta_cache, template),
    )


def rodar_votos(
    alvo: str,
    arvore: ArvoreTemas,
    caminho_candidatos: Path,
    classificadores: tuple[ClassificadorLLM, ClassificadorLLM],
    pasta_saida: Path = CAMINHOS.intermediarios,
    limite: int | None = None,
) -> Path:
    df = carregar_questoes() if alvo == "questoes" else carregar_corpus()
    candidatos = {linha["id"]: candidatos_de_dict(linha["candidatos"]) for linha in ler_jsonl(caminho_candidatos)}
    openai, anthropic = classificadores
    linhas: list[dict] = []
    for posicao, (id_, texto) in enumerate(zip(df["id"], df["texto"])):
        if limite is not None and posicao >= limite:
            break
        lista = candidatos[str(id_)]
        voto_a = openai.classificar(texto, lista, arvore)
        voto_b = anthropic.classificar(texto, lista, arvore)
        linhas.append({
            "id": str(id_),
            "openai": None if voto_a is None else voto_a.model_dump(),
            "anthropic": None if voto_b is None else voto_b.model_dump(),
        })
        if (posicao + 1) % 25 == 0:
            registro.info("%d questões votadas", posicao + 1)
    saida = pasta_saida / f"votos_llm_{alvo}.jsonl"
    escrever_jsonl(saida, linhas)
    registro.info(
        "gravado %s; chamadas openai=%d anthropic=%d, cache openai=%d anthropic=%d",
        saida, openai.chamadas, anthropic.chamadas, openai.acertos_cache, anthropic.acertos_cache,
    )
    return saida


def verificar_provedores() -> dict[str, str]:
    resultado: dict[str, str] = {}
    for provedor, variavel_modelo, padrao, variavel_chave in (
        ("openai", "MODELO_OPENAI", "gpt-5", "OPENAI_API_KEY"),
        ("anthropic", "MODELO_ANTHROPIC", "claude-sonnet-5-5", "ANTHROPIC_API_KEY"),
    ):
        if not ler_env(variavel_chave):
            resultado[provedor] = f"sem {variavel_chave}"
            continue
        try:
            invocar = criar_invocador(provedor, ler_env(variavel_modelo, padrao) or padrao)
            voto = invocar(
                "Questão de teste: o crime de furto está no Código Penal. "
                "Candidatos:\n- id 1: Penal > Furto\nResponda escolhendo o id 1 com confiança 1."
            )
            resultado[provedor] = "ok" if voto.tema_central_id == 1 else f"respondeu {voto.tema_central_id}"
        except Exception as erro:
            resultado[provedor] = f"erro: {erro}"
    return resultado


def main(argumentos: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Colhe os votos dos dois modelos de linguagem.")
    parser.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")
    parser.add_argument("--passada", type=int, choices=[1, 2], default=2)
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--verificar", action="store_true")
    args = parser.parse_args(argumentos)
    if args.verificar:
        for provedor, estado in verificar_provedores().items():
            print(f"{provedor}: {estado}")
        return
    caminho = CAMINHOS.intermediarios / f"candidatos_{args.alvo}_p{args.passada}.jsonl"
    rodar_votos(args.alvo, ArvoreTemas.carregar(), caminho, criar_classificadores(), limite=args.limite)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/test_llm.py -v`
Expected: 11 PASS.

- [ ] **Step 6: Verificar os provedores reais**

Pré-requisito: `.env` na raiz com `OPENAI_API_KEY` e `ANTHROPIC_API_KEY`. Se o arquivo não existir, pular este passo e dizer isso no relatório da tarefa.

Run: `uv run python -m classificador.llm --verificar`
Expected: `openai: ok` e `anthropic: ok`. Se um provedor devolver erro de modelo inexistente, ajustar `MODELO_OPENAI` ou `MODELO_ANTHROPIC` no `.env` para um modelo disponível de custo médio e registrar qual foi usado no relatório da tarefa. Se a OpenAI reclamar de `reasoning_effort`, remover o argumento e registrar.

- [ ] **Step 7: Commit**

```bash
git add src/classificador/llm.py src/classificador/prompts/classificar.md tests/test_llm.py
git commit -m "Votos dos dois modelos com saída estruturada, cache e retentativas"
```

---

### Task 9: Voto por vizinhança sobre o corpus

**Files:**
- Create: `src/classificador/vizinhanca.py`, `tests/test_vizinhanca.py`

**Interfaces:**
- Consumes: `Indice`, `criar_indice`, `montar_indice_corpus`, `ArvoreTemas`, `carregar_questoes`, `carregar_corpus`, `escrever_jsonl`.
- Produces:
  - `K_VIZINHOS = 10`
  - `@dataclass(frozen=True) Vizinho(id: str, tema_id: int, similaridade: float)`
  - `@dataclass(frozen=True) VotoVizinhanca(tema_nivel2: int | None, peso_nivel2: float, tema_nivel1: int | None, peso_nivel1: float, vizinhos: list[Vizinho])` com `para_dict() -> dict` e `VotoVizinhanca.de_dict(d) -> VotoVizinhanca`.
  - `votar_vizinhanca(texto, indice_corpus, arvore, k=K_VIZINHOS, excluir=frozenset()) -> VotoVizinhanca`. Cada vizinho publicável vota com peso igual à similaridade, truncada em zero. No nível 1 todo vizinho vota no seu ancestral de nível 1. No nível 2 só vizinhos com tema de nível 2 votam no próprio tema. O peso devolvido é a soma do vencedor dividida pela soma de todos os vizinhos publicáveis, nos dois níveis. Sem vizinhos, tudo `None` e `0.0`.
  - `rodar_vizinhanca(alvo, arvore, embeddings, pasta_saida=CAMINHOS.intermediarios, caminho_corpus=CAMINHOS.corpus, criar=criar_indice) -> Path`. Sem arquivo de corpus, grava votos nulos para todas as questões. Para `alvo == "corpus"`, exclui a própria questão.
  - `main()` com `--alvo`.

- [ ] **Step 1: Escrever os testes**

`tests/test_vizinhanca.py`:

```python
import pandas as pd
import pytest

from classificador import vizinhanca as modulo
from classificador.arvore import ArvoreTemas
from classificador.candidatos import montar_indice_corpus
from classificador.dados import ler_jsonl
from classificador.indice import IndiceMemoria
from classificador.vizinhanca import VotoVizinhanca, votar_vizinhanca
from tests.fakes import EmbeddingsFalsas


def criar_memoria(nome, embeddings):
    return IndiceMemoria(nome, embeddings)


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def indice_com(arvore, linhas):
    corpus = pd.DataFrame(linhas)
    return montar_indice_corpus(corpus, arvore, EmbeddingsFalsas(), criar=criar_memoria)


def test_vizinhos_votam_nos_dois_niveis(arvore):
    indice = indice_com(arvore, [
        {"id": "C1", "tema_id": 5527, "texto": "pronuncia e impronuncia no juri"},
        {"id": "C2", "tema_id": 5527, "texto": "desclassificacao pelo juiz sumariante"},
        {"id": "C3", "tema_id": 5528, "texto": "sessao de julgamento do juri"},
    ])
    voto = votar_vizinhanca("pronuncia e impronuncia no juri", indice, arvore, k=3)
    assert voto.tema_nivel1 == 5524
    assert voto.peso_nivel1 == pytest.approx(1.0)
    assert voto.tema_nivel2 in {5527, 5528}
    assert 0 < voto.peso_nivel2 <= 1.0
    assert voto.vizinhos[0].id == "C1"
    assert voto.vizinhos[0].similaridade == pytest.approx(1.0, abs=1e-6)


def test_vizinho_de_nivel1_vota_so_no_nivel1(arvore):
    indice = indice_com(arvore, [{"id": "C1", "tema_id": 5524, "texto": "texto"}])
    voto = votar_vizinhanca("texto", indice, arvore)
    assert voto.tema_nivel1 == 5524 and voto.peso_nivel1 == pytest.approx(1.0)
    assert voto.tema_nivel2 is None and voto.peso_nivel2 == 0.0


def test_tema_duplicado_no_corpus_e_canonicalizado(arvore):
    indice = indice_com(arvore, [{"id": "C1", "tema_id": 6724, "texto": "texto"}])
    voto = votar_vizinhanca("texto", indice, arvore)
    assert voto.tema_nivel1 == 4704
    assert voto.vizinhos[0].tema_id == 4704


def test_corpus_vazio_e_exclusao_devolvem_voto_nulo(arvore):
    vazio = indice_com(arvore, [])
    nulo = votar_vizinhanca("texto", vazio, arvore)
    assert nulo == VotoVizinhanca(None, 0.0, None, 0.0, [])
    um = indice_com(arvore, [{"id": "C1", "tema_id": 5524, "texto": "texto"}])
    assert votar_vizinhanca("texto", um, arvore, excluir=frozenset({"C1"})).tema_nivel1 is None


def test_ida_e_volta_dict(arvore):
    indice = indice_com(arvore, [{"id": "C1", "tema_id": 5527, "texto": "texto"}])
    voto = votar_vizinhanca("texto", indice, arvore)
    assert VotoVizinhanca.de_dict(voto.para_dict()) == voto


def test_rodar_sem_corpus_grava_votos_nulos(arvore, tmp_path):
    saida = modulo.rodar_vizinhanca(
        "questoes", arvore, EmbeddingsFalsas(), pasta_saida=tmp_path,
        caminho_corpus=tmp_path / "nao_existe.jsonl", criar=criar_memoria,
    )
    linhas = ler_jsonl(saida)
    assert len(linhas) == 359
    assert linhas[0]["tema_nivel1"] is None and linhas[0]["vizinhos"] == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_vizinhanca.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.vizinhanca`.

- [ ] **Step 3: Implementar `vizinhanca.py`**

```python
"""Voto por vizinhança: as questões do corpus mais próximas votam no tema delas."""
from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from langchain_core.embeddings import Embeddings

from classificador.arvore import ArvoreTemas
from classificador.candidatos import montar_indice_corpus
from classificador.config import CAMINHOS
from classificador.dados import carregar_corpus, carregar_questoes, escrever_jsonl
from classificador.embeddings import criar_embeddings
from classificador.indice import Indice, criar_indice

registro = logging.getLogger(__name__)

K_VIZINHOS = 10
COLUNAS_CORPUS = ["id", "tema_id", "enunciado", "comando", "alternativas", "url", "site", "confianca_fonte", "texto"]


@dataclass(frozen=True)
class Vizinho:
    id: str
    tema_id: int
    similaridade: float


@dataclass(frozen=True)
class VotoVizinhanca:
    tema_nivel2: int | None
    peso_nivel2: float
    tema_nivel1: int | None
    peso_nivel1: float
    vizinhos: list[Vizinho]

    def para_dict(self) -> dict:
        return {
            "tema_nivel2": self.tema_nivel2,
            "peso_nivel2": self.peso_nivel2,
            "tema_nivel1": self.tema_nivel1,
            "peso_nivel1": self.peso_nivel1,
            "vizinhos": [asdict(v) for v in self.vizinhos],
        }

    @staticmethod
    def de_dict(dados: dict) -> "VotoVizinhanca":
        return VotoVizinhanca(
            tema_nivel2=None if dados.get("tema_nivel2") is None else int(dados["tema_nivel2"]),
            peso_nivel2=float(dados.get("peso_nivel2", 0.0)),
            tema_nivel1=None if dados.get("tema_nivel1") is None else int(dados["tema_nivel1"]),
            peso_nivel1=float(dados.get("peso_nivel1", 0.0)),
            vizinhos=[Vizinho(str(v["id"]), int(v["tema_id"]), float(v["similaridade"])) for v in dados.get("vizinhos", [])],
        )


VOTO_NULO = VotoVizinhanca(None, 0.0, None, 0.0, [])


def _vencedor(pesos: dict[int, float], total: float) -> tuple[int | None, float]:
    if not pesos or total <= 0:
        return None, 0.0
    tema = max(pesos, key=lambda t: pesos[t])
    return tema, pesos[tema] / total


def votar_vizinhanca(
    texto: str,
    indice_corpus: Indice,
    arvore: ArvoreTemas,
    k: int = K_VIZINHOS,
    excluir: frozenset[str] = frozenset(),
) -> VotoVizinhanca:
    if indice_corpus.tamanho() == 0:
        return VOTO_NULO
    vizinhos = [
        Vizinho(r.id, arvore.canonico(int(r.metadados["tema_id"])), max(r.similaridade, 0.0))
        for r in indice_corpus.buscar(texto, k, excluir)
    ]
    pesos1: dict[int, float] = defaultdict(float)
    pesos2: dict[int, float] = defaultdict(float)
    total = 0.0
    for v in vizinhos:
        if not arvore.publicavel(v.tema_id):
            continue
        total += v.similaridade
        pesos1[arvore.ancestral_nivel1(v.tema_id)] += v.similaridade
        if arvore.nivel(v.tema_id) == 2:
            pesos2[v.tema_id] += v.similaridade
    tema1, peso1 = _vencedor(pesos1, total)
    tema2, peso2 = _vencedor(pesos2, total)
    return VotoVizinhanca(tema2, peso2, tema1, peso1, vizinhos)


def rodar_vizinhanca(
    alvo: str,
    arvore: ArvoreTemas,
    embeddings: Embeddings,
    pasta_saida: Path = CAMINHOS.intermediarios,
    caminho_corpus: Path = CAMINHOS.corpus,
    criar=criar_indice,
) -> Path:
    corpus = carregar_corpus(caminho_corpus) if caminho_corpus.exists() else pd.DataFrame(columns=COLUNAS_CORPUS)
    if len(corpus) == 0:
        registro.warning("corpus ausente ou vazio em %s; votos de vizinhança serão nulos", caminho_corpus)
    indice = montar_indice_corpus(corpus, arvore, embeddings, criar)
    df = carregar_questoes() if alvo == "questoes" else corpus
    linhas: list[dict] = []
    for id_, texto in zip(df["id"], df["texto"]):
        excluir = frozenset({str(id_)}) if alvo == "corpus" else frozenset()
        voto = votar_vizinhanca(texto, indice, arvore, excluir=excluir)
        linhas.append({"id": str(id_), **voto.para_dict()})
    saida = pasta_saida / f"vizinhanca_{alvo}.jsonl"
    escrever_jsonl(saida, linhas)
    registro.info("gravado %s com %d linhas", saida, len(linhas))
    return saida


def main(argumentos: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Voto por vizinhança sobre o corpus de referência.")
    parser.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")
    args = parser.parse_args(argumentos)
    rodar_vizinhanca(args.alvo, ArvoreTemas.carregar(), criar_embeddings())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_vizinhanca.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/classificador/vizinhanca.py tests/test_vizinhanca.py
git commit -m "Voto por vizinhança em dois níveis sobre o corpus de referência"
```

---

### Task 10: Regras de decisão

**Files:**
- Create: `src/classificador/decisao.py`, `tests/test_decisao.py`

**Interfaces:**
- Consumes: `VotoModelo`, `VotoVizinhanca`, `Candidato`, `candidatos_de_dict`, `ArvoreTemas`, `ler_jsonl`, `escrever_jsonl`.
- Produces:
  - `@dataclass(frozen=True) Limiares(publicar: float = 0.80, pai: float = 0.70, contradicao: float = 0.60)` com `para_dict()` e `Limiares.de_dict(d)`.
  - `@dataclass Decisao(id: str, decisao: str, tema_central_id: int | None, extras_ids: list[int], confianca: float | None, motivo: str, regra: int)` com `para_dict()`.
  - `decidir(id_, voto_a, voto_b, vizinhanca, candidatos, arvore, limiares) -> Decisao`.
  - `carregar_limiares(pasta=CAMINHOS.intermediarios) -> Limiares`: lê `limiares.json` se existir, senão os padrões.
  - `rodar_decisoes(alvo, arvore, limiares, pasta=CAMINHOS.intermediarios, passada=2) -> Path`. Lê `votos_llm_<alvo>.jsonl`, `vizinhanca_<alvo>.jsonl` (opcional) e `candidatos_<alvo>_p<passada>.jsonl`; grava `decisoes_<alvo>.jsonl`.
- Regras, aplicadas nesta ordem. `a` e `b` são os votos; `anc(t)` é o ancestral de nível 1.
  - **7.** `a` ou `b` é `None`: `revisar`, sugestão é o tema do voto que existe; sem nenhum voto, o primeiro candidato. Motivo "modelo sem resposta válida".
  - **1.** `a.disciplina == b.disciplina == "Outra"`: `fora`, motivo "fora das quatro disciplinas: " mais a justificativa de `a`.
  - **6.** Os dois com tema `None`: se nenhum diz "Outra", `fora` com motivo "nenhum tema da árvore cobre o assunto: " mais a justificativa de `a`; senão `revisar` com o primeiro candidato e motivo "um modelo diz fora das disciplinas, outro diz que nenhum candidato serve". Só um com tema `None`: `revisar` com o tema do outro, motivo "um modelo não achou candidato; sugestão do outro".
  - **2.** Mesmo tema: se `min(conf) >= limiares.publicar` e a vizinhança não contradiz com força, `publicar`. Contradiz com força significa `vizinhanca.tema_nivel1` definido, `peso_nivel1 >= limiares.contradicao` e `anc(tema) != vizinhanca.tema_nivel1`.
  - **5.** Mesmo tema, mas confiança baixa ou contradição: `revisar` com esse tema e motivo dizendo qual dos dois.
  - **3.** Temas diferentes no mesmo ramo: `pai = anc(a.tema)`; se `min(conf) >= limiares.pai`, `publicar` no pai, extras recebem os dois temas que não são o pai; senão `revisar` com o pai e motivo "irmãos abaixo do limiar do pai".
  - **4.** Ramos diferentes: `revisar`. Sugestão: o voto cujo ramo é o `tema_nivel1` da vizinhança; sem isso, o de maior confiança, empate para `a`. Motivo "modelos divergem: " com os dois caminhos.
  - `confianca`: `min` nas regras 2 e 3; a do voto sugerido nas 4, 5, 6 e 7; `None` em `fora` e quando nenhum voto existe.
  - `extras_ids`: união dos extras dos votos mais, na regra 3, os dois temas; sem o central, sem repetição, só publicáveis.
  - Nunca `publicar` em tema que não é publicável. `revisar` sempre tem `tema_central_id`.

- [ ] **Step 1: Escrever os testes**

`tests/test_decisao.py`:

```python
import pytest

from classificador import decisao as modulo
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato
from classificador.dados import escrever_jsonl, ler_jsonl
from classificador.decisao import Limiares, decidir
from classificador.llm import VotoModelo
from classificador.vizinhanca import VotoVizinhanca

L = Limiares(publicar=0.8, pai=0.7, contradicao=0.6)
CAND = [Candidato(5524, "tema", 0.7), Candidato(5527, "tema", 0.6), Candidato(5528, "tema", 0.5), Candidato(5159, "tema", 0.4)]


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def v(tema, conf=0.9, disciplina="Processo Penal", extras=()):
    return VotoModelo(tema_central_id=tema, extras_ids=list(extras), disciplina=disciplina, confianca=conf, justificativa="porque sim")


def viz(n1=None, p1=0.0, n2=None, p2=0.0):
    return VotoVizinhanca(n2, p2, n1, p1, [])


def d(a, b, vz=None, limiares=L, arvore=None):
    return decidir("Q1", a, b, vz, CAND, arvore, limiares)


def test_regra1_fora_quando_ambos_outra(arvore):
    r = d(v(None, 0.3, "Outra"), v(None, 0.2, "Outra"), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("fora", None, 1)
    assert r.motivo.startswith("fora das quatro disciplinas")
    assert r.confianca is None


def test_regra2_publica_quando_concordam(arvore):
    r = d(v(5527, 0.9, extras=[5528]), v(5527, 0.85, extras=[5524]), viz(5524, 0.9, 5527, 0.8), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("publicar", 5527, 2)
    assert r.confianca == pytest.approx(0.85)
    assert set(r.extras_ids) == {5528, 5524}
    assert r.motivo == ""


def test_regra5_revisa_quando_concordam_abaixo_do_limiar(arvore):
    r = d(v(5527, 0.9), v(5527, 0.7), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5527, 5)
    assert "limiar" in r.motivo


def test_regra5_revisa_quando_vizinhanca_contradiz_com_forca(arvore):
    forte = d(v(5527), v(5527), viz(5543, 0.7), arvore=arvore)
    assert (forte.decisao, forte.regra) == ("revisar", 5)
    assert "vizinhan" in forte.motivo
    fraca = d(v(5527), v(5527), viz(5543, 0.5), arvore=arvore)
    assert fraca.decisao == "publicar"


def test_regra3_publica_no_pai_quando_irmaos(arvore):
    r = d(v(5527, 0.8), v(5528, 0.75), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("publicar", 5524, 3)
    assert set(r.extras_ids) == {5527, 5528}
    assert r.confianca == pytest.approx(0.75)


def test_regra3_publica_no_pai_quando_pai_e_filho(arvore):
    r = d(v(5524, 0.9), v(5527, 0.8), arvore=arvore)
    assert (r.decisao, r.tema_central_id) == ("publicar", 5524)
    assert r.extras_ids == [5527]


def test_regra3_revisa_abaixo_do_limiar_do_pai(arvore):
    r = d(v(5527, 0.6), v(5528, 0.9), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5524, 3)


def test_regra4_sugere_pelo_ramo_da_vizinhanca(arvore):
    r = d(v(5527, 0.9), v(5159, 0.6), viz(5157, 0.8), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5159, 4)
    assert r.confianca == pytest.approx(0.6)
    assert "divergem" in r.motivo


def test_regra4_sem_vizinhanca_usa_maior_confianca_e_empate_vai_para_a(arvore):
    assert d(v(5527, 0.6), v(5159, 0.9), arvore=arvore).tema_central_id == 5159
    assert d(v(5527, 0.7), v(5159, 0.7), arvore=arvore).tema_central_id == 5527


def test_dois_temas_de_nivel1_diferentes_nunca_publicam_na_raiz(arvore):
    r = d(v(5543, 0.95), v(5590, 0.95), arvore=arvore)
    assert r.decisao == "revisar" and r.regra == 4
    assert r.tema_central_id in {5543, 5590}


def test_regra6_fora_quando_ambos_nenhum_nas_disciplinas(arvore):
    r = d(v(None, 0.4), v(None, 0.3, "Penal"), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("fora", None, 6)
    assert r.motivo.startswith("nenhum tema da árvore cobre o assunto")


def test_regra6_revisa_quando_um_outra_e_um_nenhum(arvore):
    r = d(v(None, 0.4, "Outra"), v(None, 0.3), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5524, 6)


def test_regra6_revisa_quando_so_um_nenhum(arvore):
    r = d(v(None, 0.4), v(5527, 0.7), arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5527, 6)
    assert r.confianca == pytest.approx(0.7)


def test_regra7_um_modelo_falhou(arvore):
    r = d(v(5527, 0.9), None, arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra) == ("revisar", 5527, 7)
    assert r.motivo == "modelo sem resposta válida"


def test_regra7_nenhum_voto_usa_primeiro_candidato(arvore):
    r = d(None, None, arvore=arvore)
    assert (r.decisao, r.tema_central_id, r.regra, r.confianca) == ("revisar", 5524, 7, None)


def test_extras_nao_incluem_central_inativo_nem_raiz(arvore):
    r = d(v(5527, extras=[5527, 5078, 5062, 5528]), v(5527), arvore=arvore)
    assert r.extras_ids == [5528]


def test_extras_canonicalizam_duplicados(arvore):
    r = d(v(5527, extras=[6724]), v(5527), arvore=arvore)
    assert r.extras_ids == [4704]


def test_limiares_ida_e_volta():
    assert Limiares.de_dict(L.para_dict()) == L


def test_rodar_decisoes_grava(arvore, tmp_path):
    escrever_jsonl(tmp_path / "votos_llm_questoes.jsonl", [
        {"id": "Q1", "openai": v(5527).model_dump(), "anthropic": v(5527).model_dump()},
    ])
    escrever_jsonl(tmp_path / "candidatos_questoes_p2.jsonl", [
        {"id": "Q1", "candidatos": [{"tema_id": 5527, "origem": "tema", "similaridade": 0.5}]},
    ])
    saida = modulo.rodar_decisoes("questoes", arvore, L, pasta=tmp_path)
    linhas = ler_jsonl(saida)
    assert linhas[0]["decisao"] == "publicar" and linhas[0]["tema_central_id"] == 5527
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_decisao.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.decisao`.

- [ ] **Step 3: Implementar `decisao.py`**

```python
"""As sete regras que decidem entre publicar, revisar e fora."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato, candidatos_de_dict
from classificador.config import CAMINHOS
from classificador.dados import escrever_jsonl, ler_jsonl
from classificador.llm import VotoModelo
from classificador.vizinhanca import VotoVizinhanca

registro = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limiares:
    publicar: float = 0.80
    pai: float = 0.70
    contradicao: float = 0.60

    def para_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def de_dict(dados: dict) -> "Limiares":
        return Limiares(float(dados["publicar"]), float(dados["pai"]), float(dados["contradicao"]))


@dataclass
class Decisao:
    id: str
    decisao: str
    tema_central_id: int | None
    extras_ids: list[int] = field(default_factory=list)
    confianca: float | None = None
    motivo: str = ""
    regra: int = 0

    def para_dict(self) -> dict:
        return asdict(self)


def _extras(arvore: ArvoreTemas, central: int | None, *fontes: list[int]) -> list[int]:
    saida: list[int] = []
    for fonte in fontes:
        for tema in fonte:
            if not arvore.existe(tema):
                continue
            canonico = arvore.canonico(tema)
            if arvore.publicavel(canonico) and canonico != central and canonico not in saida:
                saida.append(canonico)
    return saida


def _contradiz(vizinhanca: VotoVizinhanca | None, tema: int, arvore: ArvoreTemas, limiares: Limiares) -> bool:
    if vizinhanca is None or vizinhanca.tema_nivel1 is None:
        return False
    return vizinhanca.peso_nivel1 >= limiares.contradicao and arvore.ancestral_nivel1(tema) != vizinhanca.tema_nivel1


def decidir(
    id_: str,
    voto_a: VotoModelo | None,
    voto_b: VotoModelo | None,
    vizinhanca: VotoVizinhanca | None,
    candidatos: list[Candidato],
    arvore: ArvoreTemas,
    limiares: Limiares,
) -> Decisao:
    primeiro_candidato = candidatos[0].tema_id if candidatos else None

    # Regra 7: algum modelo não respondeu.
    if voto_a is None or voto_b is None:
        existente = voto_a or voto_b
        if existente is not None and existente.tema_central_id is not None:
            return Decisao(id_, "revisar", existente.tema_central_id, _extras(arvore, existente.tema_central_id, existente.extras_ids),
                           existente.confianca, "modelo sem resposta válida", 7)
        return Decisao(id_, "revisar", primeiro_candidato, [], None, "modelo sem resposta válida", 7)

    # Regra 1: os dois dizem que a questão é de outra disciplina.
    if voto_a.disciplina == "Outra" and voto_b.disciplina == "Outra":
        return Decisao(id_, "fora", None, [], None, f"fora das quatro disciplinas: {voto_a.justificativa}", 1)

    ta, tb = voto_a.tema_central_id, voto_b.tema_central_id

    # Regra 6: um ou os dois não acharam candidato.
    if ta is None and tb is None:
        if voto_a.disciplina != "Outra" and voto_b.disciplina != "Outra":
            return Decisao(id_, "fora", None, [], None, f"nenhum tema da árvore cobre o assunto: {voto_a.justificativa}", 6)
        return Decisao(id_, "revisar", primeiro_candidato, [], None,
                       "um modelo diz fora das disciplinas, outro diz que nenhum candidato serve", 6)
    if ta is None or tb is None:
        outro = voto_b if ta is None else voto_a
        assert outro.tema_central_id is not None
        return Decisao(id_, "revisar", outro.tema_central_id, _extras(arvore, outro.tema_central_id, outro.extras_ids),
                       outro.confianca, "um modelo não achou candidato; sugestão do outro", 6)

    assert ta is not None and tb is not None
    conf_min = min(voto_a.confianca, voto_b.confianca)

    # Regras 2 e 5: mesmo tema.
    if ta == tb:
        extras = _extras(arvore, ta, voto_a.extras_ids, voto_b.extras_ids)
        if _contradiz(vizinhanca, ta, arvore, limiares):
            assert vizinhanca is not None and vizinhanca.tema_nivel1 is not None
            motivo = f"vizinhança aponta {arvore.caminho(vizinhanca.tema_nivel1)} com peso {vizinhanca.peso_nivel1:.2f}"
            return Decisao(id_, "revisar", ta, extras, conf_min, motivo, 5)
        if conf_min < limiares.publicar:
            return Decisao(id_, "revisar", ta, extras, conf_min, f"confiança {conf_min:.2f} abaixo do limiar {limiares.publicar:.2f}", 5)
        return Decisao(id_, "publicar", ta, extras, conf_min, "", 2)

    # Regra 3: temas diferentes no mesmo ramo.
    if arvore.mesmo_ramo(ta, tb):
        pai = arvore.ancestral_nivel1(ta)
        extras = _extras(arvore, pai, [ta, tb], voto_a.extras_ids, voto_b.extras_ids)
        if conf_min >= limiares.pai:
            return Decisao(id_, "publicar", pai, extras, conf_min, "", 3)
        return Decisao(id_, "revisar", pai, extras, conf_min,
                       f"irmãos {arvore.titulo(ta)} e {arvore.titulo(tb)} abaixo do limiar do pai {limiares.pai:.2f}", 3)

    # Regra 4: ramos diferentes. Sugestão: o voto apoiado pela vizinhança; sem apoio, o de maior confiança.
    escolhido: VotoModelo | None = None
    if vizinhanca is not None and vizinhanca.tema_nivel1 is not None:
        if arvore.ancestral_nivel1(ta) == vizinhanca.tema_nivel1:
            escolhido = voto_a
        elif arvore.ancestral_nivel1(tb) == vizinhanca.tema_nivel1:
            escolhido = voto_b
    if escolhido is None:
        escolhido = voto_b if voto_b.confianca > voto_a.confianca else voto_a
    assert escolhido.tema_central_id is not None
    motivo = f"modelos divergem: {arvore.caminho(ta)} vs {arvore.caminho(tb)}"
    return Decisao(id_, "revisar", escolhido.tema_central_id,
                   _extras(arvore, escolhido.tema_central_id, [ta, tb], voto_a.extras_ids, voto_b.extras_ids),
                   escolhido.confianca, motivo, 4)


def carregar_limiares(pasta: Path = CAMINHOS.intermediarios) -> Limiares:
    arquivo = pasta / "limiares.json"
    if arquivo.exists():
        return Limiares.de_dict(json.loads(arquivo.read_text(encoding="utf-8")))
    registro.warning("limiares.json ausente; usando os padrões %s", Limiares())
    return Limiares()


def rodar_decisoes(
    alvo: str,
    arvore: ArvoreTemas,
    limiares: Limiares,
    pasta: Path = CAMINHOS.intermediarios,
    passada: int = 2,
) -> Path:
    votos = ler_jsonl(pasta / f"votos_llm_{alvo}.jsonl")
    caminho_viz = pasta / f"vizinhanca_{alvo}.jsonl"
    vizinhancas = {l["id"]: VotoVizinhanca.de_dict(l) for l in ler_jsonl(caminho_viz)} if caminho_viz.exists() else {}
    candidatos = {l["id"]: candidatos_de_dict(l["candidatos"]) for l in ler_jsonl(pasta / f"candidatos_{alvo}_p{passada}.jsonl")}
    linhas: list[dict] = []
    for linha in votos:
        id_ = linha["id"]
        voto_a = None if linha.get("openai") is None else VotoModelo.model_validate(linha["openai"])
        voto_b = None if linha.get("anthropic") is None else VotoModelo.model_validate(linha["anthropic"])
        decisao = decidir(id_, voto_a, voto_b, vizinhancas.get(id_), candidatos.get(id_, []), arvore, limiares)
        if decisao.decisao == "publicar":
            assert decisao.tema_central_id is not None and arvore.publicavel(decisao.tema_central_id)
        if decisao.decisao == "revisar":
            assert decisao.tema_central_id is not None
        linhas.append(decisao.para_dict())
    saida = pasta / f"decisoes_{alvo}.jsonl"
    escrever_jsonl(saida, linhas)
    contagem = {d: sum(1 for l in linhas if l["decisao"] == d) for d in ("publicar", "revisar", "fora")}
    registro.info("gravado %s: %s", saida, contagem)
    return saida
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_decisao.py -v`
Expected: 20 PASS. Atenção ao teste de empate na regra 4: com confianças iguais e sem vizinhança, a sugestão é a de `a`.

- [ ] **Step 5: Commit**

```bash
git add src/classificador/decisao.py tests/test_decisao.py
git commit -m "Regras de decisão entre publicar, revisar e fora com recuo ao pai"
```

---

### Task 11: Escrita e validação de `publicacao.csv`

**Files:**
- Create: `src/classificador/saida.py`, `tests/test_saida.py`

**Interfaces:**
- Consumes: `ArvoreTemas`, `CAMINHOS.publicacao`.
- Produces:
  - `COLUNAS = ["id", "decisao", "tema_central_id", "extras_ids", "confianca", "motivo"]`
  - `montar_publicacao(decisoes: list[dict]) -> pd.DataFrame`: uma linha por decisão, tudo como texto. `tema_central_id` vazio quando `None`; `extras_ids` unidos por `;`; `confianca` com duas casas ou vazio; `motivo` como veio.
  - `validar_publicacao(df: pd.DataFrame, ids_esperados: list[str], arvore) -> list[str]`: lista de mensagens de erro, vazia quando válido.
  - `escrever_publicacao(decisoes: list[dict], ids_esperados: list[str], arvore, caminho=CAMINHOS.publicacao) -> Path`: valida e grava; levanta `ValueError` com todos os erros se houver algum.
  - `ler_publicacao(caminho=CAMINHOS.publicacao) -> pd.DataFrame` com tudo como texto.
- Validações: colunas exatas e na ordem; ids únicos e iguais ao conjunto esperado; `decisao` em `{publicar, revisar, fora}`; `publicar` e `revisar` com `tema_central_id` inteiro e publicável; `fora` com `tema_central_id` vazio; `revisar` e `fora` com `motivo` não vazio; `confianca` vazia ou número entre 0 e 1; cada extra existe, é publicável e é diferente do central.

- [ ] **Step 1: Escrever os testes**

`tests/test_saida.py`:

```python
import pytest

from classificador import saida
from classificador.arvore import ArvoreTemas


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def decisoes_validas():
    return [
        {"id": "Q0001", "decisao": "publicar", "tema_central_id": 5527, "extras_ids": [5524], "confianca": 0.9, "motivo": "", "regra": 2},
        {"id": "Q0002", "decisao": "revisar", "tema_central_id": 5159, "extras_ids": [], "confianca": 0.55, "motivo": "dúvida", "regra": 4},
        {"id": "Q0003", "decisao": "fora", "tema_central_id": None, "extras_ids": [], "confianca": None, "motivo": "tributário", "regra": 1},
    ]


def test_montar_publicacao_formata_tudo_como_texto():
    df = saida.montar_publicacao(decisoes_validas())
    assert list(df.columns) == saida.COLUNAS
    assert df.loc[0].tolist() == ["Q0001", "publicar", "5527", "5524", "0.90", ""]
    assert df.loc[2].tolist() == ["Q0003", "fora", "", "", "", "tributário"]


def test_validacao_aceita_decisoes_validas(arvore):
    df = saida.montar_publicacao(decisoes_validas())
    assert saida.validar_publicacao(df, ["Q0001", "Q0002", "Q0003"], arvore) == []


@pytest.mark.parametrize("alteracao, trecho", [
    ({"id": "Q0001"}, "repetid"),
    ({"decisao": "talvez"}, "decisao"),
    ({"tema_central_id": None}, "tema_central_id"),
    ({"tema_central_id": 6724}, "publicável"),
    ({"tema_central_id": 5062}, "publicável"),
    ({"confianca": 1.5}, "confianca"),
    ({"extras_ids": [5159, 5159]}, "extras"),
    ({"extras_ids": [5159]}, "extras"),
])
def test_validacao_acusa_erros(arvore, alteracao, trecho):
    decisoes = decisoes_validas()
    decisoes[1].update(alteracao)
    df = saida.montar_publicacao(decisoes)
    erros = saida.validar_publicacao(df, ["Q0001", "Q0002", "Q0003"], arvore)
    assert erros and any(trecho in e for e in erros)


def test_validacao_exige_motivo_em_revisar_e_fora_e_ids_completos(arvore):
    decisoes = decisoes_validas()
    decisoes[1]["motivo"] = ""
    df = saida.montar_publicacao(decisoes)
    erros = saida.validar_publicacao(df, ["Q0001", "Q0002", "Q0003", "Q0004"], arvore)
    assert any("motivo" in e for e in erros)
    assert any("Q0004" in e for e in erros)


def test_escrever_e_ler(arvore, tmp_path):
    caminho = tmp_path / "publicacao.csv"
    saida.escrever_publicacao(decisoes_validas(), ["Q0001", "Q0002", "Q0003"], arvore, caminho)
    df = saida.ler_publicacao(caminho)
    assert df.loc[0, "tema_central_id"] == "5527"
    assert df.loc[2, "tema_central_id"] == ""
    assert caminho.read_text(encoding="utf-8").splitlines()[0] == "id,decisao,tema_central_id,extras_ids,confianca,motivo"


def test_escrever_recusa_invalido(arvore, tmp_path):
    decisoes = decisoes_validas()
    decisoes[0]["tema_central_id"] = 6724
    with pytest.raises(ValueError, match="publicável"):
        saida.escrever_publicacao(decisoes, ["Q0001", "Q0002", "Q0003"], arvore, tmp_path / "p.csv")
```

Os dois últimos casos da parametrização cobrem extra repetido e extra igual ao central da linha 2, que tem central 5159.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_saida.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.saida`.

- [ ] **Step 3: Implementar `saida.py`**

```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_saida.py -v`
Expected: 13 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/classificador/saida.py tests/test_saida.py
git commit -m "Escrita e validação do publicacao.csv"
```

---

### Task 12: Calibração, escolha de limiares e `previsao.txt`

**Files:**
- Create: `src/classificador/calibracao.py`, `tests/test_calibracao.py`

**Interfaces:**
- Consumes: `decidir`, `Limiares`, `VotoModelo`, `VotoVizinhanca`, `Candidato`, `candidatos_de_dict`, `ArvoreTemas`, `carregar_corpus`, `carregar_ancora_manual`, `ler_jsonl`, `config.SEMENTE`.
- Produces:
  - `FAIXAS = [(0.0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]` e `faixa_de(confianca: float | None) -> str` com rótulos `"0.0-0.6"`, `"0.6-0.7"`, `"0.7-0.8"`, `"0.8-0.9"`, `"0.9-1.0"` e `"sem"` para `None`.
  - `@dataclass Entrada(id: str, voto_a: VotoModelo | None, voto_b: VotoModelo | None, vizinhanca: VotoVizinhanca | None, candidatos: list[Candidato], verdadeiro: int | None)`.
  - `carregar_entradas(alvo, pasta, arvore, passada=2) -> list[Entrada]`: lê votos, vizinhança e candidatos; para `alvo == "corpus"` preenche `verdadeiro` com o tema canônico do corpus.
  - `decidir_todas(entradas, arvore, limiares) -> list[Decisao]`.
  - `avaliar(decisoes, entradas, arvore) -> pd.DataFrame` com colunas `id, decisao, regra, confianca, faixa, tema_decidido, tema_verdadeiro, acerto`. `acerto` é `True`, `False` ou `None` quando não há tema decidido ou verdadeiro.
  - `tabela_faixas(avaliacao) -> pd.DataFrame` só com `publicar`, agrupada por `regra` e `faixa`, colunas `n, acertos, precisao`.
  - `precisao_reponderada(tabela, avaliacao_questoes) -> float`: para cada publicada das 359, a precisão do par `(regra, faixa)` no corpus; sem o par, a da `faixa`; sem a faixa, a global do corpus. Média ponderada por contagem. Sem publicadas, `0.0`.
  - `bootstrap_precisao(avaliacao_corpus, avaliacao_questoes, repeticoes, semente=SEMENTE) -> tuple[float, float]`: reamostra as publicadas do corpus com reposição, recalcula tabela e reponderação, devolve percentis 2,5 e 97,5.
  - `varrer_limiares(entradas_corpus, entradas_questoes, arvore, grade, contradicao=0.6, repeticoes=200) -> pd.DataFrame` com colunas `publicar, pai, n_publicadas, cobertura, precisao_corpus, precisao_prevista, limite_inferior, limite_superior`.
  - `escolher_limiares(varredura, alvo=0.97, piso=0.95, contradicao=0.6) -> Limiares`: entre as linhas com `precisao_prevista >= alvo` e `limite_inferior >= piso`, a de maior cobertura; empate, maior precisão prevista. Sem nenhuma, a de maior `limite_inferior`, com aviso.
  - `comparar_ancora(avaliacao_questoes, ancora: pd.DataFrame, arvore, tabela) -> dict` com `n_publicadas_na_ancora, acertos, precisao_observada, precisao_prevista_para_elas`.
  - `ajustar_intervalo(limite_inferior, limite_superior, observado: float | None) -> tuple[float, float]`: alarga até conter o observado.
  - `montar_texto_previsao(resumo: dict) -> str` e `escrever_previsao(caminho, precisao, intervalo, cobertura, intervalo_cobertura, texto) -> Path`, no formato exato do LEIA-ME.
  - `rodar_calibracao(arvore, pasta=CAMINHOS.intermediarios, caminho_ancora=CAMINHOS.ancora_manual, contradicao=0.6, repeticoes_varredura=200, repeticoes_final=1000) -> dict`: orquestra tudo, grava `calibracao_varredura.csv`, `calibracao_faixas.csv`, `avaliacao_corpus.csv`, `limiares.json` e `calibracao_resumo.json`, devolve o resumo. Levanta `FileNotFoundError` claro se `votos_llm_corpus.jsonl` não existe.

- [ ] **Step 1: Escrever os testes**

`tests/test_calibracao.py`:

```python
import re

import pandas as pd
import pytest

from classificador import calibracao as cal
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato
from classificador.decisao import Limiares
from classificador.llm import VotoModelo


@pytest.fixture(scope="module")
def arvore():
    return ArvoreTemas.carregar()


def v(tema, conf):
    return VotoModelo(tema_central_id=tema, extras_ids=[], disciplina="Processo Penal", confianca=conf, justificativa="")


def entrada(id_, tema_a, tema_b, conf, verdadeiro):
    return cal.Entrada(id_, v(tema_a, conf), v(tema_b, conf), None, [Candidato(tema_a, "tema", 0.5)], verdadeiro)


def corpus_sintetico():
    """20 questões: confiança 0.95 sempre certa; 0.65 certa na metade."""
    entradas = []
    for i in range(10):
        entradas.append(entrada(f"C{i}", 5527, 5527, 0.95, 5527))
    for i in range(10, 20):
        verdadeiro = 5527 if i % 2 == 0 else 5159
        entradas.append(entrada(f"C{i}", 5527, 5527, 0.65, verdadeiro))
    return entradas


def questoes_sinteticas():
    return [entrada(f"Q{i}", 5527, 5527, 0.95 if i < 4 else 0.65, None) for i in range(8)]


def test_faixa_de():
    assert cal.faixa_de(None) == "sem"
    assert cal.faixa_de(0.0) == "0.0-0.6"
    assert cal.faixa_de(0.6) == "0.6-0.7"
    assert cal.faixa_de(0.9) == "0.9-1.0"
    assert cal.faixa_de(1.0) == "0.9-1.0"


def test_tabela_faixas_mede_precisao_no_corpus(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    entradas = corpus_sintetico()
    avaliacao = cal.avaliar(cal.decidir_todas(entradas, arvore, limiares), entradas, arvore)
    tabela = cal.tabela_faixas(avaliacao).set_index(["regra", "faixa"])
    assert tabela.loc[(2, "0.9-1.0"), "precisao"] == pytest.approx(1.0)
    assert tabela.loc[(2, "0.6-0.7"), "precisao"] == pytest.approx(0.5)
    assert tabela.loc[(2, "0.6-0.7"), "n"] == 10


def test_precisao_reponderada_usa_a_distribuicao_das_questoes(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    corpus = corpus_sintetico()
    aval_c = cal.avaliar(cal.decidir_todas(corpus, arvore, limiares), corpus, arvore)
    questoes = questoes_sinteticas()
    aval_q = cal.avaliar(cal.decidir_todas(questoes, arvore, limiares), questoes, arvore)
    tabela = cal.tabela_faixas(aval_c)
    # 4 publicadas a 1.0 e 4 a 0.5 -> 0.75
    assert cal.precisao_reponderada(tabela, aval_q) == pytest.approx(0.75)


def test_bootstrap_devolve_intervalo_que_contem_a_estimativa(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    corpus = corpus_sintetico()
    aval_c = cal.avaliar(cal.decidir_todas(corpus, arvore, limiares), corpus, arvore)
    questoes = questoes_sinteticas()
    aval_q = cal.avaliar(cal.decidir_todas(questoes, arvore, limiares), questoes, arvore)
    inferior, superior = cal.bootstrap_precisao(aval_c, aval_q, repeticoes=100)
    assert 0.0 <= inferior <= 0.75 <= superior <= 1.0


def test_varredura_e_escolha_preferem_cobertura_com_precisao(arvore):
    varredura = cal.varrer_limiares(corpus_sintetico(), questoes_sinteticas(), arvore, grade=[0.6, 0.9], repeticoes=50)
    assert set(varredura.columns) >= {"publicar", "pai", "cobertura", "precisao_prevista", "limite_inferior", "limite_superior"}
    assert len(varredura) == 4
    escolhido = cal.escolher_limiares(varredura, alvo=0.97, piso=0.95)
    assert escolhido.publicar == pytest.approx(0.9)
    linha = varredura[(varredura.publicar == 0.9) & (varredura.pai == 0.9)].iloc[0]
    assert linha["cobertura"] == pytest.approx(0.5)
    assert linha["precisao_prevista"] == pytest.approx(1.0)


def test_escolher_limiares_sem_candidato_pega_maior_limite_inferior():
    varredura = pd.DataFrame([
        {"publicar": 0.6, "pai": 0.6, "cobertura": 0.9, "precisao_prevista": 0.80, "limite_inferior": 0.70, "limite_superior": 0.9},
        {"publicar": 0.9, "pai": 0.9, "cobertura": 0.5, "precisao_prevista": 0.93, "limite_inferior": 0.88, "limite_superior": 0.98},
    ])
    assert cal.escolher_limiares(varredura).publicar == pytest.approx(0.9)


def test_comparar_ancora_e_ajustar_intervalo(arvore):
    limiares = Limiares(publicar=0.6, pai=0.6)
    questoes = questoes_sinteticas()
    aval_q = cal.avaliar(cal.decidir_todas(questoes, arvore, limiares), questoes, arvore)
    ancora = pd.DataFrame({"id": ["Q0", "Q1", "Q2"], "tema_id": [5527, 5524, 5159]})
    corpus = corpus_sintetico()
    tabela = cal.tabela_faixas(cal.avaliar(cal.decidir_todas(corpus, arvore, limiares), corpus, arvore))
    resultado = cal.comparar_ancora(aval_q, ancora, arvore, tabela)
    assert resultado["n_publicadas_na_ancora"] == 3
    assert resultado["acertos"] == 2
    assert resultado["precisao_observada"] == pytest.approx(2 / 3)
    assert cal.ajustar_intervalo(0.9, 0.99, 0.95) == (0.9, 0.99)
    assert cal.ajustar_intervalo(0.9, 0.99, 0.8) == (0.8, 0.99)
    assert cal.ajustar_intervalo(0.9, 0.95, None) == (0.9, 0.95)


def test_escrever_previsao_segue_o_formato(tmp_path):
    caminho = cal.escrever_previsao(tmp_path / "previsao.txt", 0.971, (0.95, 0.99), 0.6, (0.59, 0.61), "explicação")
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    assert re.fullmatch(r"precisao_prevista: 0\.97\s+# fração das publicadas que estará certa", linhas[0])
    assert linhas[1] == "precisao_intervalo: 0.95-0.99"
    assert re.fullmatch(r"cobertura_prevista: 0\.60\s+# fração das questões que você publicou", linhas[2])
    assert linhas[3] == "cobertura_intervalo: 0.59-0.61"
    assert linhas[5] == "explicação"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_calibracao.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.calibracao`.

- [ ] **Step 3: Implementar `calibracao.py`**

```python
"""Calibração: precisão por faixa no corpus, reponderação, varredura de limiares, âncora e previsao.txt."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from classificador.ancora import carregar_ancora_manual
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato, candidatos_de_dict
from classificador.config import CAMINHOS, SEMENTE
from classificador.dados import carregar_corpus, ler_jsonl
from classificador.decisao import Decisao, Limiares, decidir
from classificador.llm import VotoModelo
from classificador.vizinhanca import VotoVizinhanca

registro = logging.getLogger(__name__)

FAIXAS = [(0.0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
ROTULOS = ["0.0-0.6", "0.6-0.7", "0.7-0.8", "0.8-0.9", "0.9-1.0"]
GRADE_PADRAO = [round(x, 2) for x in np.arange(0.5, 0.951, 0.05)]


def faixa_de(confianca: float | None) -> str:
    if confianca is None or (isinstance(confianca, float) and np.isnan(confianca)):
        return "sem"
    for (inicio, fim), rotulo in zip(FAIXAS, ROTULOS):
        if inicio <= confianca < fim:
            return rotulo
    return ROTULOS[-1]


@dataclass
class Entrada:
    id: str
    voto_a: VotoModelo | None
    voto_b: VotoModelo | None
    vizinhanca: VotoVizinhanca | None
    candidatos: list[Candidato]
    verdadeiro: int | None


def carregar_entradas(alvo: str, pasta: Path, arvore: ArvoreTemas, passada: int = 2) -> list[Entrada]:
    caminho_votos = pasta / f"votos_llm_{alvo}.jsonl"
    if not caminho_votos.exists():
        raise FileNotFoundError(f"{caminho_votos} não existe; rode os votos de '{alvo}' antes de calibrar")
    votos = ler_jsonl(caminho_votos)
    caminho_viz = pasta / f"vizinhanca_{alvo}.jsonl"
    vizinhancas = {l["id"]: VotoVizinhanca.de_dict(l) for l in ler_jsonl(caminho_viz)} if caminho_viz.exists() else {}
    candidatos = {l["id"]: candidatos_de_dict(l["candidatos"]) for l in ler_jsonl(pasta / f"candidatos_{alvo}_p{passada}.jsonl")}
    verdadeiros: dict[str, int] = {}
    if alvo == "corpus":
        corpus = carregar_corpus()
        verdadeiros = {str(i): arvore.canonico(int(t)) for i, t in zip(corpus["id"], corpus["tema_id"])}
    entradas = []
    for linha in votos:
        id_ = linha["id"]
        entradas.append(Entrada(
            id=id_,
            voto_a=None if linha.get("openai") is None else VotoModelo.model_validate(linha["openai"]),
            voto_b=None if linha.get("anthropic") is None else VotoModelo.model_validate(linha["anthropic"]),
            vizinhanca=vizinhancas.get(id_),
            candidatos=candidatos.get(id_, []),
            verdadeiro=verdadeiros.get(id_),
        ))
    return entradas


def decidir_todas(entradas: list[Entrada], arvore: ArvoreTemas, limiares: Limiares) -> list[Decisao]:
    return [decidir(e.id, e.voto_a, e.voto_b, e.vizinhanca, e.candidatos, arvore, limiares) for e in entradas]


def avaliar(decisoes: list[Decisao], entradas: list[Entrada], arvore: ArvoreTemas) -> pd.DataFrame:
    verdadeiros = {e.id: e.verdadeiro for e in entradas}
    linhas = []
    for d in decisoes:
        verdadeiro = verdadeiros.get(d.id)
        acerto = None
        if d.tema_central_id is not None and verdadeiro is not None:
            acerto = arvore.acerto(d.tema_central_id, verdadeiro)
        linhas.append({
            "id": d.id, "decisao": d.decisao, "regra": d.regra, "confianca": d.confianca,
            "faixa": faixa_de(d.confianca), "tema_decidido": d.tema_central_id,
            "tema_verdadeiro": verdadeiro, "acerto": acerto,
        })
    return pd.DataFrame(linhas, columns=["id", "decisao", "regra", "confianca", "faixa", "tema_decidido", "tema_verdadeiro", "acerto"])


def tabela_faixas(avaliacao: pd.DataFrame) -> pd.DataFrame:
    publicadas = avaliacao[(avaliacao["decisao"] == "publicar") & avaliacao["acerto"].notna()].copy()
    if publicadas.empty:
        return pd.DataFrame(columns=["regra", "faixa", "n", "acertos", "precisao"])
    publicadas["acerto"] = publicadas["acerto"].astype(bool)
    grupo = publicadas.groupby(["regra", "faixa"])["acerto"].agg(n="size", acertos="sum").reset_index()
    grupo["precisao"] = grupo["acertos"] / grupo["n"]
    return grupo


def precisao_reponderada(tabela: pd.DataFrame, avaliacao_questoes: pd.DataFrame) -> float:
    publicadas = avaliacao_questoes[avaliacao_questoes["decisao"] == "publicar"]
    if publicadas.empty or tabela.empty:
        return 0.0
    por_par = {(int(r.regra), r.faixa): float(r.precisao) for r in tabela.itertuples()}
    por_faixa_df = tabela.groupby("faixa")[["n", "acertos"]].sum()
    por_faixa = {f: float(r.acertos / r.n) for f, r in por_faixa_df.iterrows()}
    global_ = float(tabela["acertos"].sum() / tabela["n"].sum())
    soma = 0.0
    for linha in publicadas.itertuples():
        chave = (int(linha.regra), linha.faixa)
        soma += por_par.get(chave, por_faixa.get(linha.faixa, global_))
    return soma / len(publicadas)


def bootstrap_precisao(
    avaliacao_corpus: pd.DataFrame,
    avaliacao_questoes: pd.DataFrame,
    repeticoes: int,
    semente: int = SEMENTE,
) -> tuple[float, float]:
    publicadas = avaliacao_corpus[(avaliacao_corpus["decisao"] == "publicar") & avaliacao_corpus["acerto"].notna()]
    if publicadas.empty:
        return 0.0, 0.0
    gerador = np.random.default_rng(semente)
    estimativas = []
    for _ in range(repeticoes):
        indices = gerador.integers(0, len(publicadas), len(publicadas))
        amostra = publicadas.iloc[indices]
        estimativas.append(precisao_reponderada(tabela_faixas(amostra), avaliacao_questoes))
    return float(np.percentile(estimativas, 2.5)), float(np.percentile(estimativas, 97.5))


def varrer_limiares(
    entradas_corpus: list[Entrada],
    entradas_questoes: list[Entrada],
    arvore: ArvoreTemas,
    grade: list[float] = GRADE_PADRAO,
    contradicao: float = 0.6,
    repeticoes: int = 200,
) -> pd.DataFrame:
    linhas = []
    total = len(entradas_questoes)
    for publicar in grade:
        for pai in grade:
            limiares = Limiares(publicar=publicar, pai=pai, contradicao=contradicao)
            aval_c = avaliar(decidir_todas(entradas_corpus, arvore, limiares), entradas_corpus, arvore)
            aval_q = avaliar(decidir_todas(entradas_questoes, arvore, limiares), entradas_questoes, arvore)
            tabela = tabela_faixas(aval_c)
            n_pub = int((aval_q["decisao"] == "publicar").sum())
            precisao_corpus = float(tabela["acertos"].sum() / tabela["n"].sum()) if not tabela.empty else 0.0
            inferior, superior = bootstrap_precisao(aval_c, aval_q, repeticoes)
            linhas.append({
                "publicar": publicar, "pai": pai, "n_publicadas": n_pub,
                "cobertura": n_pub / total if total else 0.0,
                "precisao_corpus": precisao_corpus,
                "precisao_prevista": precisao_reponderada(tabela, aval_q),
                "limite_inferior": inferior, "limite_superior": superior,
            })
    return pd.DataFrame(linhas)


def escolher_limiares(varredura: pd.DataFrame, alvo: float = 0.97, piso: float = 0.95, contradicao: float = 0.6) -> Limiares:
    aptas = varredura[(varredura["precisao_prevista"] >= alvo) & (varredura["limite_inferior"] >= piso)]
    if aptas.empty:
        registro.warning("nenhum par de limiares atinge precisão %.2f com piso %.2f; usando o de maior limite inferior", alvo, piso)
        melhor = varredura.sort_values(["limite_inferior", "cobertura"], ascending=[False, False]).iloc[0]
    else:
        melhor = aptas.sort_values(["cobertura", "precisao_prevista"], ascending=[False, False]).iloc[0]
    return Limiares(publicar=float(melhor["publicar"]), pai=float(melhor["pai"]), contradicao=contradicao)


def comparar_ancora(avaliacao_questoes: pd.DataFrame, ancora: pd.DataFrame, arvore: ArvoreTemas, tabela: pd.DataFrame) -> dict:
    rotulos = {str(i): int(t) for i, t in zip(ancora["id"], ancora["tema_id"])}
    publicadas = avaliacao_questoes[(avaliacao_questoes["decisao"] == "publicar") & avaliacao_questoes["id"].isin(rotulos)]
    if publicadas.empty:
        return {"n_publicadas_na_ancora": 0, "acertos": 0, "precisao_observada": None, "precisao_prevista_para_elas": None}
    acertos = sum(arvore.acerto(int(l.tema_decidido), rotulos[l.id]) for l in publicadas.itertuples())
    return {
        "n_publicadas_na_ancora": int(len(publicadas)),
        "acertos": int(acertos),
        "precisao_observada": acertos / len(publicadas),
        "precisao_prevista_para_elas": precisao_reponderada(tabela, publicadas),
    }


def ajustar_intervalo(inferior: float, superior: float, observado: float | None) -> tuple[float, float]:
    if observado is None:
        return inferior, superior
    return min(inferior, observado), max(superior, observado)


def escrever_previsao(
    caminho: Path,
    precisao: float,
    intervalo: tuple[float, float],
    cobertura: float,
    intervalo_cobertura: tuple[float, float],
    texto: str,
) -> Path:
    conteudo = (
        f"precisao_prevista: {precisao:.2f}   # fração das publicadas que estará certa\n"
        f"precisao_intervalo: {intervalo[0]:.2f}-{intervalo[1]:.2f}\n"
        f"cobertura_prevista: {cobertura:.2f}  # fração das questões que você publicou\n"
        f"cobertura_intervalo: {intervalo_cobertura[0]:.2f}-{intervalo_cobertura[1]:.2f}\n"
        f"\n{texto.strip()}\n"
    )
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


def montar_texto_previsao(resumo: dict) -> str:
    ancora = resumo.get("ancora") or {}
    partes = [
        "Como chegamos nos números.",
        f"Não há gabarito das 359 questões, então a precisão foi estimada num corpus de referência de {resumo['n_corpus']} "
        f"questões reais de concurso com tema conhecido, coletado por agentes a partir da própria árvore de temas. "
        f"O pipeline rodou sobre esse corpus com cada questão excluída da própria vizinhança, e medimos a precisão "
        f"das publicadas por regra de decisão e faixa de confiança, com a régua da Vício: certo se igual, pai ou filho.",
        f"O corpus é mais fácil que as 359, que vieram de lixeiras. Para corrigir isso, a precisão prevista é a média das "
        f"precisões por faixa no corpus, ponderada pela distribuição de faixas que as 359 publicadas realmente têm. "
        f"Os limiares de publicação ({resumo['limiares']['publicar']:.2f} no tema, {resumo['limiares']['pai']:.2f} no pai) "
        f"foram escolhidos por varredura, maximizando cobertura sujeita a precisão prevista de pelo menos 0,97 e limite "
        f"inferior do intervalo de pelo menos 0,95. Intervalo por bootstrap com {resumo['repeticoes_final']} reamostragens.",
    ]
    if ancora.get("n_publicadas_na_ancora"):
        partes.append(
            f"Checagem com âncora manual: das {ancora['n_publicadas_na_ancora']} questões publicadas que estavam na "
            f"âncora de 40 rotuladas às cegas, {ancora['acertos']} estavam certas "
            f"(observado {ancora['precisao_observada']:.2f}, previsto {ancora['precisao_prevista_para_elas']:.2f}). "
            f"{'O intervalo foi alargado para conter a observação.' if resumo.get('intervalo_alargado') else 'A observação cabe no intervalo.'}"
        )
    else:
        partes.append("Não houve âncora manual disponível na calibração; o intervalo reflete só o corpus.")
    partes.append(
        f"Cobertura: {resumo['n_publicadas']} de {resumo['n_questoes']} questões publicadas. "
        f"É um número observado, não previsto, por isso o intervalo é estreito."
    )
    return "\n\n".join(partes)


def rodar_calibracao(
    arvore: ArvoreTemas,
    pasta: Path = CAMINHOS.intermediarios,
    caminho_ancora: Path = CAMINHOS.ancora_manual,
    contradicao: float = 0.6,
    repeticoes_varredura: int = 200,
    repeticoes_final: int = 1000,
) -> dict:
    entradas_corpus = carregar_entradas("corpus", pasta, arvore)
    entradas_questoes = carregar_entradas("questoes", pasta, arvore)
    varredura = varrer_limiares(entradas_corpus, entradas_questoes, arvore, contradicao=contradicao, repeticoes=repeticoes_varredura)
    varredura.to_csv(pasta / "calibracao_varredura.csv", index=False)
    limiares = escolher_limiares(varredura, contradicao=contradicao)
    (pasta / "limiares.json").write_text(json.dumps(limiares.para_dict(), indent=2), encoding="utf-8")

    aval_c = avaliar(decidir_todas(entradas_corpus, arvore, limiares), entradas_corpus, arvore)
    aval_q = avaliar(decidir_todas(entradas_questoes, arvore, limiares), entradas_questoes, arvore)
    aval_c.to_csv(pasta / "avaliacao_corpus.csv", index=False)
    tabela = tabela_faixas(aval_c)
    tabela.to_csv(pasta / "calibracao_faixas.csv", index=False)
    precisao = precisao_reponderada(tabela, aval_q)
    inferior, superior = bootstrap_precisao(aval_c, aval_q, repeticoes_final)

    ancora_resultado = None
    if caminho_ancora.exists():
        ancora_resultado = comparar_ancora(aval_q, carregar_ancora_manual(arvore, caminho_ancora), arvore, tabela)
    else:
        registro.warning("âncora manual ausente em %s; intervalo reflete só o corpus", caminho_ancora)
    observado = None if ancora_resultado is None else ancora_resultado["precisao_observada"]
    inferior_final, superior_final = ajustar_intervalo(inferior, superior, observado)

    n_pub = int((aval_q["decisao"] == "publicar").sum())
    cobertura = n_pub / len(aval_q)
    resumo = {
        "limiares": limiares.para_dict(),
        "n_corpus": len(entradas_corpus),
        "n_questoes": len(aval_q),
        "n_publicadas": n_pub,
        "cobertura": cobertura,
        "cobertura_intervalo": [max(0.0, cobertura - 0.01), min(1.0, cobertura + 0.01)],
        "precisao_prevista": precisao,
        "precisao_intervalo": [inferior_final, superior_final],
        "intervalo_bruto": [inferior, superior],
        "intervalo_alargado": (inferior_final, superior_final) != (inferior, superior),
        "ancora": ancora_resultado,
        "repeticoes_final": repeticoes_final,
    }
    (pasta / "calibracao_resumo.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
    registro.info("limiares %s; precisão prevista %.3f [%.3f, %.3f]; cobertura %.3f", limiares, precisao, inferior_final, superior_final, cobertura)
    return resumo
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_calibracao.py -v`
Expected: 9 PASS. O teste de varredura leva alguns segundos por causa do bootstrap.

- [ ] **Step 5: Commit**

```bash
git add src/classificador/calibracao.py tests/test_calibracao.py
git commit -m "Calibração por faixa no corpus, varredura de limiares, âncora e previsao.txt"
```

---

### Task 13: CLI `classificar`, orquestração e README mínimo

**Files:**
- Create: `src/classificador/pipeline.py`, `tests/test_pipeline.py`
- Modify: `README.md` (substitui o enunciado da Vício, que já está preservado em `docs/case/README-vicio.md`)

**Interfaces:**
- Consumes: todas as funções `rodar_*` das tarefas anteriores, `escrever_publicacao`, `escrever_previsao`, `montar_texto_previsao`, `carregar_limiares`.
- Produces:
  - Funções de etapa, todas sem argumentos obrigatórios além dos nomeados: `etapa_candidatos(passada: int, alvo: str = "questoes")`, `etapa_ancora()`, `etapa_votos(alvo: str, limite: int | None = None)`, `etapa_vizinhanca(alvo: str)`, `etapa_calibrar()`, `etapa_decidir(alvo: str = "questoes")`, `etapa_publicar()`.
  - `ETAPAS_TUDO: list[tuple[str, Callable[[], None]]]` na ordem: candidatos p1 questões, âncora, candidatos p2 questões, candidatos p2 corpus, votos questões, votos corpus, vizinhança questões, vizinhança corpus, calibrar, decidir, publicar.
  - `rodar_tudo(etapas=ETAPAS_TUDO) -> None`: exige `CAMINHOS.corpus` existente, senão `FileNotFoundError` com instrução.
  - `main(argv=None)`: subcomandos `candidatos`, `ancora`, `votos`, `vizinhanca`, `calibrar`, `decidir`, `publicar`, `tudo`.
- `etapa_publicar` lê `decisoes_questoes.jsonl` e `calibracao_resumo.json`, grava `publicacao.csv` validado e `previsao.txt`, e imprime a contagem por decisão.

- [ ] **Step 1: Escrever os testes**

`tests/test_pipeline.py`:

```python
import pytest

from classificador import pipeline


def test_tudo_roda_as_etapas_na_ordem(monkeypatch, tmp_path):
    chamadas = []
    etapas = [(nome, (lambda n=nome: chamadas.append(n))) for nome, _ in pipeline.ETAPAS_TUDO]
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("", encoding="utf-8")
    monkeypatch.setattr(pipeline, "caminho_corpus", lambda: corpus)
    pipeline.rodar_tudo(etapas)
    assert chamadas == [nome for nome, _ in pipeline.ETAPAS_TUDO]
    assert chamadas[0].startswith("candidatos p1") and chamadas[-1] == "publicar"


def test_tudo_sem_corpus_falha_com_instrucao(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "caminho_corpus", lambda: tmp_path / "nao_existe.jsonl")
    with pytest.raises(FileNotFoundError, match="corpus"):
        pipeline.rodar_tudo([])


def test_main_despacha_subcomando(monkeypatch):
    recebido = {}
    monkeypatch.setattr(pipeline, "etapa_votos", lambda alvo, limite=None: recebido.update(alvo=alvo, limite=limite))
    pipeline.main(["votos", "--alvo", "corpus", "--limite", "5"])
    assert recebido == {"alvo": "corpus", "limite": 5}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL com `ModuleNotFoundError: classificador.pipeline`.

- [ ] **Step 3: Implementar `pipeline.py`**

```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -v`
Expected: toda a suíte PASS, com 1 SKIPPED do Weaviate.

- [ ] **Step 5: Fumaça de ponta a ponta sem corpus e sem chaves**

Run: `uv run classificar candidatos --passada 1`
Expected: se não houver `OPENAI_API_KEY` no `.env` nem cache de embeddings, falha com `ChaveAusenteError` mencionando `OPENAI_API_KEY`. Com a chave, grava `data/intermediarios/candidatos_questoes_p1.jsonl` com 359 linhas e `temas_alvo_corpus.json`, e imprime quantos temas alvo existem. Registrar esse número no relatório da tarefa: ele define o tamanho da coleta do corpus.

Run: `uv run classificar ancora`
Expected: `data/ancora_para_rotular.csv` com 40 linhas.

- [ ] **Step 6: Escrever o README mínimo**

Substituir o conteúdo de `README.md` por:

```markdown
# Classificação de tópicos: case Vício

Pipeline que classifica 359 questões de Penal, Processo Penal, Legislação Penal Especial e Criminologia nos temas da plataforma da Vício, decidindo entre `publicar`, `revisar` e `fora`. O enunciado original está em `docs/case/`.

## Como rodar

```bash
uv python install 3.12 && uv sync
cp .env.example .env            # chaves opcionais: o cache commitado reproduz tudo sem elas
docker compose up -d            # Weaviate; opcional, há substituto em memória
uv run classificar tudo
```

`uv run classificar tudo` gera `publicacao.csv` e `previsao.txt` na raiz. As etapas também rodam separadas: `candidatos`, `ancora`, `votos`, `vizinhanca`, `calibrar`, `decidir`, `publicar`. Testes: `uv run pytest`.

## O que gera cada arquivo

| Arquivo | Gerado por |
|---|---|
| `data/intermediarios/candidatos_*.jsonl` | `classificar candidatos` |
| `data/ancora_para_rotular.csv` | `classificar ancora` |
| `data/intermediarios/votos_llm_*.jsonl` | `classificar votos` |
| `data/intermediarios/vizinhanca_*.jsonl` | `classificar vizinhanca` |
| `data/intermediarios/limiares.json`, `calibracao_*.csv`, `calibracao_resumo.json` | `classificar calibrar` |
| `data/intermediarios/decisoes_questoes.jsonl` | `classificar decidir` |
| `publicacao.csv`, `previsao.txt` | `classificar publicar` |

## Documentos

- Spec de design: `docs/projeto/specs/2026-10-14-classificacao-topicos-design.md`
- Plano do pipeline: `docs/projeto/plans/2026-10-14-pipeline-central.md`

As seções de decisões manuais, modelos usados, custo e tempo entram ao final da execução.
```

- [ ] **Step 7: Commit**

```bash
git add src/classificador/pipeline.py tests/test_pipeline.py README.md
git commit -m "CLI classificar com todas as etapas e README mínimo"
```

---

## Depois deste plano

Este plano entrega o pipeline. O restante da spec vem em planos curtos, nesta ordem:

1. **Protocolo de coleta do corpus** (não é código): lê-se `temas_alvo_corpus.json`, divide-se em lotes e disparam-se agentes de pesquisa baseados em LLM com o prompt de coleta; depois deduplica contra as 359 por embedding e grava `data/corpus_referencia.jsonl`. O prompt e os critérios de confiança das fontes vão para o relatório.
2. **Rotulagem da âncora**: Gilson preenche `data/ancora_para_rotular.csv` às cegas e consolida o resultado em `data/ancora_manual.csv`.
3. **Execução do pipeline** nas 359 e no corpus, com as chaves reais, e commit do cache.
4. **Análise exploratória** em `analise/`.
5. **API e tela de revisão**.
6. **Relatório, memo e README final**.

## Autorrevisão do plano

Cobertura da spec: seções 4 a 8, 10, 11, 15, 16 e os entregáveis `publicacao.csv` e `previsao.txt` estão nas tarefas 1 a 13. Seção 9 (corpus), 12 (análise), 13 (API), 14 (tela) e 17 (documentos finais) ficam para os planos seguintes, listados acima.

Desvios da spec, todos registrados: cliente Weaviate direto em vez do wrapper LangChain; `revisar` sem nenhum voto usa o primeiro candidato da busca como sugestão; a confiança de `fora` fica vazia no CSV; os temas duplicados nunca são candidatos, então o prompt não menciona temas sem descrição.

Consistência de nomes conferida entre tarefas: `Candidato`, `candidatos_de_dict`, `montar_indice_corpus`, `VotoModelo`, `VotoVizinhanca`, `Limiares`, `Decisao`, `decidir`, `carregar_limiares`, `rodar_*`, `escrever_publicacao`, `escrever_previsao`, `montar_texto_previsao`, `caminho_corpus`.

