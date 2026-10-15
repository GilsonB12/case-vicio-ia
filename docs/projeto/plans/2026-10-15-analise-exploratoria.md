# Análise exploratória dos dados: plano de implementação

**Goal:** Entregar `analise/analise_exploratoria.ipynb` (executado, com saídas) e `analise/achados.md`, cobrindo a seção 12 da spec: visão geral dos dados, defeitos da árvore, evidência das lixeiras, casos destacados e a heurística de corrupção de OCR da seção 5.

**Architecture:** Funções de análise reutilizáveis ficam em `analise/heuristicas.py`, testadas com pytest. O notebook é construído por `analise/construir_notebook.py` com `nbformat` e executado no lugar com `nbconvert`, para ser reproduzível por um comando. `achados.md` é escrito a partir das saídas executadas e cita ids reais.

**Tech Stack:** pandas, matplotlib, nbformat, nbconvert, ipykernel, jupyter; o pacote `classificador` já existente para carga e árvore.

**Spec:** `docs/projeto/specs/2026-10-14-classificacao-topicos-design.md`, seções 5 (heurística de OCR) e 12.

## Global Constraints

- Tudo em português; identificadores sem acento; commits em português sem trailers; `git add` por caminho explícito.
- Nada aqui chama API de modelo. A parte da spec que compara `assunto_origem` com a decisão do pipeline fica marcada no notebook como "preenchido após a execução" numa célula de markdown, sem código que dependa de arquivos ainda inexistentes.
- Só dados de `anexos/`. Funções de carga vêm de `classificador.dados` e `classificador.arvore`.
- Gráficos poucos e úteis, no máximo cinco, com matplotlib; antes de desenhar, invocar o skill `dataviz` e seguir sua paleta e regras de forma.
- Toda afirmação de `achados.md` sobre um id de questão ou tema precisa ser verificável no notebook.
- Suíte completa (`uv run pytest -q`) continua verde e sem avisos.

## Review Focus

1. Heurística de OCR que marca questões legítimas com vocabulário raro (latim jurídico, siglas): o limiar e o vocabulário precisam tolerar isso; teste com um texto jurídico normal que não deve ser marcado.
2. Detector de enunciado genérico que deixa passar variantes ("Marque a opção INCORRETA", "Analise a opção CORRETA", "Assinale a alternativa correta:"); teste com as variantes reais do dataset.
3. Notebook que executa na máquina do autor mas não na do avaliador por depender de caminho absoluto ou de kernel não registrado; o teste de validade do notebook e o comando de execução documentado cobrem isso.
4. `achados.md` citando ids que não existem; teste que valida todo `Q\d{4}` e todo tema id citado.
5. Gráfico ilegível em tema escuro ou com cores aleatórias; seguir o skill `dataviz`.

---

### Task 1: Heurísticas de análise com testes

**Files:**
- Create: `analise/__init__.py` (vazio), `analise/heuristicas.py`, `tests/test_heuristicas.py`
- Modify: `pyproject.toml` (grupo dev: `matplotlib>=3.9`, `nbformat>=5.10`, `nbconvert>=7.16`, `ipykernel>=6.29`, `jupyter>=1.1`; `[tool.pytest.ini_options] pythonpath = ["."]`)

**Interfaces (Produces):**
- `montar_vocabulario(textos: Iterable[str]) -> set[str]`: tokens alfabéticos com 3 ou mais letras, minúsculos, sem acento, que aparecem em pelo menos 2 textos distintos.
- `proporcao_fora_do_vocabulario(texto: str, vocabulario: set[str]) -> float`: fração dos tokens do texto que não estão no vocabulário; 0.0 para texto sem tokens.
- `marcar_corrupcao_ocr(questoes: pd.DataFrame, limiar: float = 0.25) -> pd.DataFrame` com colunas `id, proporcao, suspeita` (bool), ordenado por `proporcao` decrescente. O vocabulário é montado com todos os textos das questões mais os caminhos e descrições dos temas, excluindo a própria questão avaliada.
- `eh_enunciado_generico(enunciado_limpo: str) -> bool`: verdadeiro quando o enunciado limpo tem até 60 caracteres e casa, sem distinção de caixa e acento, com uma destas formas: "assinale a alternativa ...", "assinale a opção ...", "marque a ...", "analise a opção ...", "julgue o item ..." ou é só "assinale a alternativa correta".
- `grupos_de_enunciado_repetido(questoes: pd.DataFrame) -> list[list[str]]`: grupos de ids com o mesmo enunciado limpo normalizado (minúsculo, sem acento, espaços colapsados), só grupos com 2 ou mais.
- `defeitos_da_arvore(temas: pd.DataFrame) -> pd.DataFrame` com colunas `tema_id, titulo, defeito` onde `defeito` é um de: `duplicado_sem_descricao` (descrição vazia e não raiz), `inativo`, `zero_questoes` (descrição contém "0 questões"), `titulo_com_erro` (título contém um dos trechos: "Estaturo", "Comeptência", "Crimonológicas", "Crimescontra", "Falso Testemunha", "Testemunhavel", "Caractéristas"), `descricao_com_caracteres_estranhos` (descrição contém caractere fora do intervalo latino, por exemplo árabe).
- `questoes_fora_do_escopo(questoes: pd.DataFrame) -> pd.DataFrame`: linhas cuja `disciplina_origem` não está em {"Penal", "Direito Penal", "Processo Penal", "Direito Processual Penal", "Direito Penal - Legislação Especial", "Criminologia"}, com colunas `id, disciplina_origem, assunto_origem, inicio` (primeiros 120 caracteres do texto).

- [ ] **Step 1: Escrever os testes** em `tests/test_heuristicas.py` cobrindo: vocabulário ignora tokens de 1 texto só; proporção 0.0 em texto vazio; `marcar_corrupcao_ocr` nas 359 marca `Q0078` como suspeita e não marca `Q0001`; `eh_enunciado_generico` é verdadeiro para "Assinale a alternativa correta.", "Marque a opção INCORRETA.", "Analise a opção CORRETA.", "Assinale a alternativa CORRETA." e falso para "Francisco foi processado pelo Ministério Público pelo delito de furto."; `grupos_de_enunciado_repetido` nas 359 contém o grupo com `Q0090` e `Q0205`, e o grupo `Q0268`/`Q0321`; `defeitos_da_arvore` marca 20 `duplicado_sem_descricao`, 2 `inativo` (5078, 5234), inclui 4696 como `titulo_com_erro` e pelo menos 1 `descricao_com_caracteres_estranhos`; `questoes_fora_do_escopo` tem exatamente 8 linhas e inclui `Q0142`.
- [ ] **Step 2: Rodar e ver falhar** (`uv run pytest tests/test_heuristicas.py -v`).
- [ ] **Step 3: Implementar** `analise/heuristicas.py` e ajustar `pyproject.toml`; `uv sync`.
- [ ] **Step 4: Rodar e ver passar**; depois a suíte completa.
- [ ] **Step 5: Commit** `Heurísticas da análise exploratória com testes`.

---

### Task 2: Notebook construído e executado

**Files:**
- Create: `analise/construir_notebook.py`, `analise/analise_exploratoria.ipynb` (gerado e executado), `tests/test_notebook_analise.py`

**Interfaces:**
- `construir_notebook.py` tem `main()` que grava `analise/analise_exploratoria.ipynb` com `nbformat.v4`; a primeira célula de código faz `import sys; sys.path.insert(0, "..")` ou equivalente robusto ao diretório de execução (usar `Path.cwd()` e procurar `pyproject.toml` subindo), para o notebook rodar tanto de `analise/` quanto da raiz.
- Comando documentado no topo do notebook e no README: `uv run python analise/construir_notebook.py && uv run jupyter nbconvert --to notebook --execute --inplace analise/analise_exploratoria.ipynb`.

Seções do notebook, cada uma com célula markdown de título e explicação curta em português:
1. Visão geral das questões: contagens por `disciplina_origem` e por `assunto_origem` (top 15), distribuição do número de alternativas, histograma do tamanho do enunciado, quantas sem comando, tags HTML usadas.
2. Árvore de temas: contagem por disciplina e nível, tabela de `defeitos_da_arvore`, lista dos 20 duplicados com seu canônico (`ArvoreTemas.duplicados()`), temas com zero questões no source.
3. Evidência das lixeiras: para os 6 assuntos de origem mais frequentes, tabela com id, início do enunciado e início da alternativa A de 8 questões; célula markdown dizendo que a comparação com a decisão do pipeline entra após a execução.
4. Casos destacados, cada um com o texto limpo impresso: `questoes_fora_do_escopo` (8 linhas), enunciados genéricos (contagem e lista de ids) e grupos repetidos, Q0078 (OCR) com sua proporção, Q0240 (tinha `\t` literal), Q0007 (personagem "Gilson"), temas com título errado, a descrição com caracteres estranhos.
5. Heurística de OCR: tabela das 10 maiores proporções com `suspeita`, e um parágrafo markdown sobre o limiar escolhido.
6. Gráficos (até 5, via `dataviz`): questões por disciplina de origem; alternativas por questão; temas por disciplina e nível; histograma do tamanho dos enunciados; proporção fora do vocabulário (top 20).
7. Implicações para o pipeline: célula markdown com 5 a 8 bullets ligando cada achado a uma decisão de desenho (alternativas no texto, canonicalização, `fora`, temas introdutórios, OCR).

- [ ] **Step 1: Escrever `tests/test_notebook_analise.py`**: o arquivo existe, é nbformat válido (`nbformat.read` + `nbformat.validate`), tem pelo menos 7 células markdown de seção, e toda célula de código tem `execution_count` não nulo (foi executado); nenhuma célula de código contém caminho absoluto com `C:` ou `D:`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** `construir_notebook.py`, invocar `dataviz` antes das células de gráfico, gerar e executar o notebook com o comando documentado. Se o kernel não for encontrado, registrar com `uv run python -m ipykernel install --user --name case-vicio` e usar `--ExecutePreprocessor.kernel_name=case-vicio`; documentar isso.
- [ ] **Step 4: Rodar e ver passar**; suíte completa.
- [ ] **Step 5: Commit** `Notebook da análise exploratória, construído e executado` (inclui o `.ipynb` com saídas).

---

### Task 3: Documento de achados

**Files:**
- Create: `analise/achados.md`, `tests/test_achados.py`
- Modify: `README.md` (seção "Análise exploratória" com o comando de reconstrução e o link para `achados.md`)

Estrutura de `achados.md`, em português claro para quem não é técnico, no máximo 3 páginas:
1. Resumo em 5 bullets.
2. Os dados: tabela com os números da visão geral.
3. A árvore de temas: defeitos encontrados com ids, e o que isso implica para o aluno e para a classificação.
4. As lixeiras: o que os assuntos de origem mais frequentes realmente contêm, com 3 exemplos por assunto (id e primeira linha).
5. Casos destacados: tabela `id | o que tem de especial | o que o pipeline faz com ele`.
6. Corrupção de OCR: como foi medida, limiar, quem foi marcado.
7. O que isso muda no pipeline: bullets.
8. O que fica para depois da execução.

- [ ] **Step 1: Escrever `tests/test_achados.py`**: todo `Q\d{4}` citado existe nas 359; todo número de 4 dígitos entre 4365 e 6738 citado como tema existe em `temas.csv`; o arquivo tem as 8 seções.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Escrever `achados.md`** a partir das saídas do notebook executado e atualizar o README.
- [ ] **Step 4: Rodar e ver passar**; suíte completa.
- [ ] **Step 5: Commit** `Achados da análise exploratória`.
