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

Os intermediários commitados em `data/intermediarios/` e o cache em `data/cache/` são o caminho de reprodução: `uv run classificar tudo` reaproveita candidatos e vizinhança prontos, lê votos e embeddings do cache e reproduz `publicacao.csv` sem chaves e sem Docker. `uv run classificar tudo --recalcular` recalcula todas as etapas (a planilha da âncora nunca é regravada), e o que não estiver no cache vai às APIs, então ele precisa das chaves no `.env`. A execução canônica usou o Weaviate via Docker (`docker compose up -d`) e os modelos de `.env.example`.

## O que gera cada arquivo

| Arquivo | Gerado por |
|---|---|
| `data/intermediarios/candidatos_*.jsonl` | `classificar candidatos` |
| `data/ancora_para_rotular.csv` | `classificar ancora` |
| `data/ancora_manual.csv` | exportado da tela de revisão (modo Âncora) a partir de `data/ancora_rotulos_modelo_*.jsonl`; protocolo e decisões em `docs/projeto/ancora.md` |
| `data/intermediarios/votos_llm_*.jsonl` | `classificar votos` |
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

## Documentos

- Spec de design: `docs/projeto/specs/2026-10-14-classificacao-topicos-design.md`
- Plano do pipeline: `docs/projeto/plans/2026-10-14-pipeline-central.md`

As seções de decisões manuais, modelos usados, custo e tempo entram ao final da execução.
