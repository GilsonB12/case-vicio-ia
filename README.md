# Classificação de tópicos: case Vício

Pipeline que classifica 359 questões de Penal, Processo Penal, Legislação Penal Especial e Criminologia nos temas da plataforma da Vício, decidindo entre `publicar`, `revisar` e `fora`. O enunciado original está em `docs/case/`.

## Resultado

| Entrega | Onde | Resumo |
|---|---|---|
| Decisões | `publicacao.csv` | 117 publicadas (33%), 241 para revisão, 1 fora |
| Autoavaliação | `previsao.txt` | precisão prevista 0,97, intervalo 0,94 a 1,00; cobertura 0,33 |
| Relatório | [`relatorio.md`](relatorio.md) | como pensei, diagnóstico, produção e memo para o professor |
| Código | `src/classificador/`, `api/`, `revisao-ui/`, `analise/` | pipeline, API, tela de revisão e análise exploratória |

## Como rodar

```bash
uv python install 3.12 && uv sync
cp .env.example .env            # chaves opcionais: o cache commitado reproduz tudo sem elas
docker compose up -d            # Weaviate; opcional, há substituto em memória
uv run classificar tudo
```

`uv run classificar tudo` gera `publicacao.csv` e `previsao.txt` na raiz. As etapas também rodam separadas: `candidatos`, `ancora`, `votos`, `reparar`, `vizinhanca`, `calibrar`, `decidir`, `publicar`. Testes: `uv run pytest`.

Os intermediários commitados em `data/intermediarios/` e o cache em `data/cache/` são o caminho de reprodução: `uv run classificar tudo` reaproveita candidatos e vizinhança prontos, lê votos e embeddings do cache e reproduz `publicacao.csv` sem chaves e sem Docker. `uv run classificar tudo --recalcular` recalcula todas as etapas (a planilha da âncora nunca é regravada), e o que não estiver no cache vai às APIs, então ele precisa das chaves no `.env`. A execução canônica usou o Weaviate via Docker (`docker compose up -d`) e os modelos de `.env.example`.

## O que gera cada arquivo

| Arquivo | Gerado por |
|---|---|
| `data/intermediarios/candidatos_*.jsonl` | `classificar candidatos` |
| `data/ancora_para_rotular.csv` | `classificar ancora` |
| `data/ancora_manual.csv` | exportado da tela de revisão (modo Âncora) a partir de `data/ancora_rotulos_modelo_*.jsonl`; protocolo e decisões em `docs/projeto/ancora.md` |
| `data/intermediarios/votos_llm_*.jsonl` | `classificar votos`; depois, `classificar reparar` substitui os votos das questões em que um modelo não achou candidato, guardando os originais em `antes_do_reparo` |
| `data/intermediarios/candidatos_*_reparo.jsonl` | `classificar reparar` (lista ampliada só das questões revotadas) |
| `data/intermediarios/vizinhanca_*.jsonl` | `classificar vizinhanca` |
| `data/intermediarios/limiares.json`, `calibracao_*.csv`, `calibracao_resumo.json` | `classificar calibrar` |
| `data/intermediarios/decisoes_questoes.jsonl` | `classificar decidir` |
| `publicacao.csv`, `previsao.txt` | `classificar publicar` |

## API

A API classifica uma questão por vez com as mesmas peças do pipeline (candidatos, os dois modelos, a vizinhança e as regras de decisão). Nada é carregado na subida: árvore, embeddings, índices e classificadores nascem na primeira requisição que precisa deles e ficam em memória.

```bash
uv run uvicorn api.main:app --reload --port 8000
```

| Rota | O que devolve |
|---|---|
| `GET /saude` | chaves de API presentes, Weaviate alcançável, corpus presente, número de votos em cache e limiares em uso |
| `GET /temas` | os 351 temas publicáveis, com `tema_id`, `caminho`, `nivel` e `disciplina` |
| `POST /classificar` | decisão (`publicar`, `revisar` ou `fora`), tema central e caminho, extras, confiança, motivo, regra, candidatos e os três votos |

```bash
curl -X POST http://127.0.0.1:8000/classificar \
  -H "Content-Type: application/json" \
  -d '{"enunciado_html": "<p>Sobre o crime de furto, assinale a alternativa correta.</p>", "comando": "", "alternativas": {"A": "É crime contra o patrimônio.", "B": "É crime contra a vida."}}'
```

`alternativas` é obrigatório e `comando` pode ser omitido, mas não nulo; fora disso a resposta é 422 apontando o campo. Sem chave de API e sem cache para a questão, a resposta é 503 com a mensagem do que falta. A documentação interativa fica em `http://127.0.0.1:8000/docs`.

## Tela de revisão

A pasta `revisao-ui/` tem a tela em que o professor revisa as questões que o classificador mandou para `revisar`. Ela lê arquivos estáticos e não chama a API nem modelo nenhum.

```bash
cd revisao-ui
npm install
npm run dados   # copia publicacao.csv, anexos/questoes.jsonl, anexos/temas.csv, os intermediários e a âncora para public/dados/
npm run dev     # abre em http://localhost:5173
```

`npm run dados` pula, com aviso, o arquivo que ainda não existe. Sem `publicacao.csv`, `questoes.jsonl` e `temas.csv` em `public/dados/`, a tela usa `public/dados-exemplo/`: 6 questões inventadas, 4 delas a revisar, com os temas da árvore real. Uma faixa no alto avisa que os dados são de exemplo.

O que a tela faz:

- À esquerda fica a fila das questões a revisar, com o id, o início do enunciado, o tema sugerido, a confiança e o motivo.
- À direita aparecem o enunciado sem HTML e as alternativas. Abaixo deles vêm a sugestão com o caminho completo, o tema e a justificativa de cada modelo e os candidatos com caminho, origem e similaridade.
- O professor confirma a sugestão, troca o tema ou marca a questão como fora. A observação é opcional. A troca oferece os candidatos da questão e uma busca, sem acento nem caixa, sobre todos os temas publicáveis. Raiz, tema inativo e duplicata sem descrição nunca aparecem.
- O contador mostra quantas questões já foram revisadas. **Exportar CSV** baixa `decisoes_professor.csv` com as colunas `id,acao,tema_id,observacao`. As decisões ficam só na memória da aba, e a tela avisa antes de fechar a aba se há decisão ainda não exportada.

No alto, a tela troca entre a **Fila de revisão** e o modo **Âncora**, em que o professor fecha o gabarito de referência das 40 questões de `data/ancora_para_rotular.csv`: para cada uma ele vê as propostas do Rotulador 1 e do Rotulador 2 (tema, confiança, justificativa e alternativas consideradas, com marca quando os dois concordam) e aceita uma delas, busca outro tema publicável ou marca fora da árvore (`tema_id` 0), com comentário opcional. As decisões ficam guardadas no navegador, e **Exportar ancora_manual.csv** baixa `id,tema_id,observacao` em UTF-8 com BOM, uma linha por questão decidida, avisando quando ainda há pendentes.

Os testes rodam com `npm test`, e `npm run build` checa os tipos e gera `dist/`.

## Análise exploratória

O notebook `analise/analise_exploratoria.ipynb` descreve as questões e os temas antes de qualquer classificação, sem chamar modelo, e já vem executado. Os achados, para quem não é técnico, estão em [`analise/achados.md`](analise/achados.md). Para reconstruir o notebook a partir de `analise/construir_notebook.py` e executá-lo no lugar:

```bash
uv run python analise/construir_notebook.py && uv run jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=600 analise/analise_exploratoria.ipynb
```

## Modelos, custo e tempo

| Peça | Escolha |
|---|---|
| Voto 1 | `claude-sonnet-5-5` (Anthropic), esforço de raciocínio baixo, saída estruturada por JSON Schema, `max_tokens` 4096 |
| Voto 2 | `gpt-5-mini` (OpenAI), esforço de raciocínio baixo, saída estruturada por JSON Schema |
| Embeddings | `text-embedding-3-large` (OpenAI), 3.072 dimensões, cache em disco |
| Banco vetorial | Weaviate 1.27 via Docker (`docker compose up -d`, porta 8081), com substituto em memória |
| Orquestração | LangChain para os modelos e os embeddings; cliente oficial do Weaviate para o índice |

Chamadas na execução canônica (16/10/2026): 752 por modelo (359 questões, 332 do corpus, 61 revotações do reparo), mais 1 de verificação por provedor. Custo real no painel da Anthropic: US$ 5,80. OpenAI: cerca de US$ 0,80 pela medição por chamada (US$ 0,001 por voto, mais centavos de embeddings). Tempo: 2 minutos de candidatos, 80 minutos de votos, 10 minutos de reparo, 1 minuto de vizinhança; calibração, decisão e publicação são instantâneas. `uv run classificar tudo` a partir do cache reproduz tudo em 25 segundos, sem chave.

A partir desta versão, cada chamada de modelo ou de embeddings grava uma linha em `data/custos/chamadas.jsonl` (tokens de entrada, saída e raciocínio, latência, custo pela tabela de preços versionada em `src/classificador/precos.json`, acerto de cache ou chamada real), e `uv run classificar custos` agrega por execução, etapa e modelo. As 1.504 chamadas da execução canônica foram feitas antes desse livro-razão existir, por isso o custo delas vem do painel do provedor e da medição por chamada.

## Decisões tomadas à mão

- **Árvore:** os 20 temas duplicados sem descrição (6716 a 6738) viram o original, 17 pelo título e 3 por uma tabela de exceções (`arvore.py`); raízes de disciplina e os 2 temas inativos nunca são publicados; os 7 temas sem questões na fonte continuam candidatos.
- **Rótulos de origem ignorados:** `disciplina_origem` e `assunto_origem` não entram no prompt nem na busca, porque 7 das 8 questões com disciplina de origem fora do escopo são penais (`analise/achados.md`).
- **Prompt congelado** em `src/classificador/prompts/classificar.md`, com a régua explicada e a proibição de escolher temas introdutórios por serem genéricos.
- **Corpus:** 100 temas de maior peso entre os candidatos das 359, 4 questões por tema, por orçamento; fontes, regra de pai e filho e níveis de confiança em `docs/projeto/coleta-corpus.md`, com uma checagem independente de 60 rótulos (88% compatíveis pela régua).
- **Calibração:** os limiares saem da varredura, não da mão; o que foi fixado à mão foi a escada de seleção (meta 0,97 de média e 0,95 de limite inferior, relaxada degrau a degrau) e a suavização de Jeffreys.
- **Âncora:** 40 questões rotuladas por dois rotuladores independentes e arbitradas pelo autor, com 6 decisões manuais, inclusive a Q0282 na raiz da disciplina (`docs/projeto/ancora.md`).
- **Depois de ver os dados:** a etapa de reparo de candidatos e a mudança da regra 6 (dois modelos sem tema vira revisar, não fora), com os números antes e depois em `docs/projeto/notes/2026-10-14-pendencias-pipeline-central.md`, seção "Execução real".

## Documentos

- Relatório e memo: [`relatorio.md`](relatorio.md)
- Spec de design: `docs/projeto/specs/2026-10-14-classificacao-topicos-design.md`
- Planos: `docs/projeto/plans/`
- Decisões e pendências: `docs/projeto/notes/2026-10-14-pendencias-pipeline-central.md`
- Âncora: `docs/projeto/ancora.md`; corpus: `docs/projeto/coleta-corpus.md`; árvore legível: `docs/projeto/arvore-temas.md`
- Análise exploratória: `analise/achados.md`
