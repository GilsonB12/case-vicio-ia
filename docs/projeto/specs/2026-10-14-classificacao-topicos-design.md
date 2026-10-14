# Spec: classificação de tópicos (case Vício)

Data: 2026-10-14. Autor: Gilson. Prazo de entrega: domingo, 2026-10-18.

## 1. Contexto e objetivo

A Vício (Método VDE) pede a reclassificação de 359 questões reais de Penal, Processo Penal, Legislação Penal Especial e Criminologia numa árvore de 377 temas. Para cada questão decidimos `publicar`, `revisar` ou `fora`. Das publicadas, pelo menos 95% precisam estar certas. Dentro disso, quanto mais publicadas, melhor. Conta como certo o tema que a equipe atribuiu ou um nó pai ou filho dele. Irmão conta como erro.

Entregamos `publicacao.csv`, `previsao.txt`, relatório, memo para o professor e o código, num repositório público.

Objetivos secundários, nesta ordem: previsão de precisão honesta e bem fundamentada; raciocínio, diagnóstico e desenho de produção claros; e demonstração natural da stack da vaga (Python, Pandas, APIs REST, OpenAI, Anthropic, LangChain, vector DB, prompt engineering, TypeScript, pesquisa na web, Git). Nenhuma tecnologia entra por enfeite.

## 2. Critérios de sucesso

1. `publicacao.csv` com 359 linhas válidas no formato do LEIA-ME.
2. Precisão real nas publicadas de 95% ou mais, com estimativa própria mirando 97% para ter margem.
3. `previsao.txt` com precisão e cobertura previstas, intervalos, e método explicado.
4. O avaliador consegue reproduzir o CSV com um comando, sem chaves de API, graças ao cache commitado.
5. Relatório de até 5 páginas com as quatro partes pedidas e memo de 1 página.
6. Toda decisão manual registrada no README.

## 3. Escopo

Dentro: pipeline de classificação, corpus de referência coletado por agentes, calibração e previsão, âncora manual, análise exploratória dos dados, API REST, tela de revisão em TypeScript, relatório, memo, README.

Fora: treinar modelos próprios, raspar sites com código no repositório, infraestrutura de deploy, autenticação na API ou na tela, persistência da tela.

## 4. Arquitetura

Cada questão passa por cinco etapas: limpeza do texto, busca de temas candidatos, três votos independentes, regras de decisão, escrita do resultado. Um único comando roda tudo e grava os intermediários em disco.

```
anexos/                        questoes.jsonl, temas.csv, LEIA-ME.md, entrega_modelo.csv
src/classificador/
  dados.py                     carga, limpeza de HTML, árvore de temas, canonicalização
  indice.py                    Weaviate (coleções temas e corpus) com fallback em memória
  candidatos.py                união das fontes de candidatos
  llm.py                       ChatOpenAI e ChatAnthropic via LangChain, saída Pydantic, cache
  prompts/classificar.md       prompt versionado
  vizinhanca.py                voto kNN sobre o corpus
  decisao.py                   regras publicar, revisar, fora
  calibracao.py                precisão por faixa, reponderação, bootstrap, previsao.txt
  pipeline.py                  CLI que encadeia tudo e gera publicacao.csv
data/
  corpus_referencia.jsonl      corpus coletado pelos agentes, com proveniência
  ancora_manual.csv            40 rótulos cegos
  cache/                       respostas de modelos e embeddings, por hash
  intermediarios/              candidatos, votos e decisões por questão
analise/
  analise_exploratoria.ipynb   notebook em Pandas
  achados.md                   achados gerais e casos destacados
api/main.py                    FastAPI
revisao-ui/                    Vite + React + TypeScript
relatorio/relatorio.md         as quatro partes
relatorio/memo_professor.md    1 página
docs/case/                     enunciado original: PDF, README da Vício, zip
tests/                         pytest
publicacao.csv  previsao.txt  README.md  docker-compose.yml  pyproject.toml  .env.example
```

Ferramentas: Python 3.12 gerenciado por uv, porque 3.14 ainda não tem wheels para todas as libs. LangChain para modelos, saída estruturada, embeddings e integração com Weaviate. Weaviate em Docker Compose. Pandas para tabelas. Node 24 para a tela.

## 5. Dados e preparação

`dados.py` carrega `questoes.jsonl` e `temas.csv` e produz dois DataFrames.

Texto de classificação de cada questão: enunciado com HTML removido, mais comando, mais alternativas numeradas. Alternativas entram porque muitos enunciados são genéricos, como "Assinale a alternativa correta", e o conteúdo está nas alternativas. Quebras de linha e espaços duplicados são normalizados. Texto com corrupção de OCR não é corrigido; é marcado por uma heurística simples de proporção de palavras fora do vocabulário e vai para o relatório.

Árvore de temas: só temas com `status = active`. A árvore oferece pai, filhos, irmãos, ancestral de nível 1 e disciplina de cada tema.

Canonicalização de duplicatas: os 20 temas com `tema_id` entre 6716 e 6738 não têm descrição nem contagem e repetem títulos de temas existentes, seja com sufixo "(Parte N)", seja em outra disciplina. O pipeline mapeia cada um para o tema canônico em duas etapas. Primeiro, automaticamente, por título normalizado sem acentos, sem o sufixo "(Parte N)" e sem distinção de maiúsculas; isso resolve, por exemplo, 6724 para 4704, 6726 e 6727 para 5199, 6732 e 6733 para 5480, 6734 para 4703. Segundo, uma tabela de exceções manuais em `dados.py` para os títulos que não casam: 6735 "Provas em Espécie" para 5543 "Provas em Espécies", 6736 "Recursos (Parte 03) - Espécies" para 5560 "Recursos em Espécies", 6722 "Estatuto do Idoso - Crimes" para 4696 "Estaturo de Idoso - Crimes". Um teste garante que todos os 20 têm destino. Nenhuma linha de `publicacao.csv` usa ids desse grupo, nem como central nem como extra; qualquer id duplicado que um modelo devolva é convertido no canônico. Esta é a decisão manual de maior risco e fica registrada no README e no relatório com a alternativa descartada.

## 6. Índice e candidatos

`indice.py` cria duas coleções no Weaviate: `Tema`, com um documento por tema ativo canônico, e `CorpusQuestao`, com uma questão do corpus por documento. Documento de tema é caminho completo mais descrição sem a contagem de questões. Embeddings da OpenAI, modelo large, via LangChain. O Weaviate é acessado pelo cliente oficial v4, não pelo wrapper do LangChain, porque o wrapper esconde a métrica de similaridade; os vetores vêm dos embeddings do LangChain. Se o Weaviate não responde, a busca cai para cosseno em memória com NumPy, com aviso no log. Embeddings ficam no cache.

`candidatos.py` monta para cada questão a união de três fontes: os 8 temas mais próximos por similaridade, os temas das 10 questões vizinhas do corpus, e o pai de todo candidato de nível 2. Teto de 12 candidatos, cortando pelos de menor similaridade. A raiz da disciplina nunca é candidata.

A busca roda em duas passadas. A primeira usa só similaridade com temas e pais, porque o corpus ainda não existe; ela define os temas alvo do corpus e a planilha da âncora. A segunda, depois do corpus coletado, acrescenta os temas dos vizinhos e é a que alimenta os votos.

## 7. Três votos

Dois votos vêm de modelos de linguagem, um da OpenAI e um da Anthropic, escolhidos por variáveis de ambiente. Os identificadores padrão são definidos na implementação após consulta à documentação atual dos provedores; o critério é o modelo de custo médio de cada um, não o mais caro. Ambos recebem o mesmo prompt via LangChain com saída estruturada Pydantic:

```
tema_central_id: int | None      None significa nenhum candidato serve
extras_ids: list[int]
disciplina: Literal[Penal, Processo Penal, Legislação Especial, Criminologia, Outra]
confianca: float entre 0 e 1
justificativa: str com no máximo 2 frases
```

O prompt, em `prompts/classificar.md`, contém: o papel, a régua da Vício resumida, a questão com alternativas, os candidatos com id, caminho e descrição, e três instruções de preferência. Preferir o subtema quando a questão é claramente sobre ele. Preferir o tema pai quando a questão cobre vários subtemas. Escolher temas introdutórios como "Conceito e Fontes do Direito Penal" ou "Princípios do Processo Penal" só quando a questão é sobre o conceito ou princípio em si, nunca porque é o tema mais genérico. O prompt não mostra `disciplina_origem` nem `assunto_origem`, porque são pouco confiáveis. Temperatura zero onde o provedor permite; a família GPT-5 só aceita o valor padrão, então nela usamos esforço de raciocínio baixo.

O terceiro voto é a vizinhança em `vizinhanca.py`: as 10 questões do corpus mais próximas votam no tema delas, ponderadas por similaridade. O voto é computado em dois níveis, subtema e ancestral de nível 1, e devolve o tema vencedor e o peso relativo em cada nível. Sem corpus, o voto é nulo e as regras tratam isso.

## 8. Regras de decisão

`decisao.py` aplica as regras em ordem, em Python puro, sobre os três votos de cada questão. Definições: "mesmo ramo" significa mesmo ancestral de nível 1; "vizinhança contradiz com força" significa que o vencedor da vizinhança no nível 1 tem peso de 0,6 ou mais e está em ramo diferente do consenso dos modelos.

1. Os dois modelos dizem `disciplina = Outra`: `fora`, motivo "fora das quatro disciplinas".
2. Os dois escolhem o mesmo `tema_central_id`, a menor confiança é maior ou igual a `limiar_publicar`, e a vizinhança não contradiz com força: `publicar` nesse tema.
3. Os dois escolhem temas no mesmo ramo, sendo irmãos ou pai e filho, e a menor confiança é maior ou igual a `limiar_pai`: `publicar` no tema de nível 1 do ramo. Se um deles já escolheu o nível 1, ele é o pai. Extras recebem os dois subtemas.
4. Os dois escolhem temas em ramos diferentes: `revisar`, sugestão é o tema apoiado pela vizinhança; sem vizinhança, o de maior confiança. Motivo cita os dois temas.
5. Os dois escolhem o mesmo tema, mas abaixo de `limiar_publicar`, ou a vizinhança contradiz com força: `revisar` com esse tema sugerido e motivo.
6. Os dois dizem `None`: `fora` se ambos dizem disciplina das quatro, motivo "nenhum tema da árvore cobre o assunto", citando o assunto que os modelos descreveram. Se só um diz `None`: `revisar` com a sugestão do outro.
7. Qualquer resposta inválida após as retentativas: `revisar` com motivo "modelo sem resposta válida".

`confianca` no CSV é a menor confiança dos dois modelos nas regras 2 e 3, e a confiança do modelo cujo tema foi sugerido nas regras 4, 5 e 6. Nas regras 1 e 7 fica vazia. Os limiares não são escolhidos à mão: saem da calibração da seção 10.

## 9. Corpus de referência

Objetivo: um conjunto de questões reais de concurso com tema conhecido, usado como voto de vizinhança e como conjunto de validação.

Temas alvo: união dos candidatos da primeira passada da seção 6 nas 359 questões, mais os pais. Estimativa: 100 a 150 temas.

Coleta: os temas alvo são divididos em 8 a 10 lotes. Para cada lote, um agente de pesquisa baseado em LLM é disparado em paralelo, com instruções de buscar em páginas públicas questões reais de concurso sobre cada tema do lote, extrair enunciado, comando e alternativas, e registrar URL, nome do site e nível de confiança da fonte. Meta de 5 a 8 questões por tema. Níveis de confiança definidos antes da coleta: alto para provas oficiais de bancas e sites de questões estabelecidos com classificação por assunto; médio para cursos preparatórios com questões comentadas; baixo para blogs. O agente não copia comentários nem gabaritos comentados, só a questão.

Pós-processamento automatizado: deduplicação interna, deduplicação contra as 359 por similaridade de embedding maior que 0,95, remoção de questões sem alternativas, e gravação em `data/corpus_referencia.jsonl` com campos `id`, `tema_id`, `enunciado`, `comando`, `alternativas`, `url`, `site`, `confianca_fonte`.

O coletor não é código do repositório. O prompt dos agentes, os critérios de confiança e as estatísticas do corpus vão para o relatório como decisão documentada. O corpus entra no repositório com a proveniência.

## 10. Calibração e previsão

`calibracao.py` roda o pipeline completo sobre o corpus, com cada questão excluída da própria vizinhança, e mede acerto com a régua da Vício: certo se o tema decidido é igual, pai ou filho do tema do corpus.

Saídas intermediárias: precisão por faixa de confiança, em 5 faixas, cruzada com a regra que decidiu. Cada célula (regra, faixa) recebe a precisão suavizada de Jeffreys, (acertos + 0,5) / (n + 1), para que células pequenas todas certas não virem certeza; célula com menos de 5 questões do corpus recua para a faixa agregada, e faixa pequena recua para o global. Como as 359 são mais difíceis que o corpus, a precisão prevista reponderada é a média, sobre as publicadas das 359, da precisão suavizada da célula onde cada uma caiu.

Escolha de limiares: varre `limiar_publicar` e `limiar_pai` em passos de 0,05, calcula precisão prevista e cobertura para cada par, e escolhe o par de maior cobertura cuja precisão prevista é de pelo menos 0,97 e cujo limite inferior do intervalo é de pelo menos 0,95.

Âncora: a seção 11 fornece 40 rótulos nas 359. A precisão observada nas publicadas da âncora é comparada à prevista para as mesmas questões. Se a diferença cabe no intervalo, o intervalo é mantido. Se não cabe, o intervalo é alargado até conter a observação e o relatório explica.

Intervalos: simulação da posterior Beta por célula com 1000 amostras (cada célula sorteia sua precisão de Beta(acertos + 0,5; erros + 0,5), e a média ponderada pelas publicadas das 359 forma a distribuição), percentis 2,5 e 97,5. Isso mantém largura honesta em células pequenas, onde o bootstrap por reamostragem colapsa. A varredura de limiares usa 200 amostras por par; os números finais e a verificação de que a meta foi atingida usam as 1000. Cobertura é observada diretamente, então seu intervalo é estreito.

`previsao.txt` segue o formato do LEIA-ME e, após as quatro linhas, explica o método, o viés do corpus, o que a âncora mostrou e os limiares escolhidos.

## 11. Âncora manual

Antes de qualquer chamada a modelos de linguagem, o pipeline gera `data/ancora_para_rotular.csv` com 40 questões das 359, sorteadas com semente fixa e estratificadas por `disciplina_origem`, cada uma com os candidatos da seção 6 e suas descrições. Gilson rotula às cegas, sem ver saída do pipeline; uma segunda passagem independente, feita por um modelo de linguagem que também não vê os votos, serve para discutir divergências. Divergências são discutidas e o rótulo final vai para `data/ancora_manual.csv` com os campos `id`, `tema_id`, `rotulador_gilson`, `rotulador_segunda_passagem`, `observacao`. O arquivo é commitado.

## 12. Análise exploratória dos dados

Entregável próprio em `analise/`. O notebook em Pandas e o `achados.md` cobrem:

Visão geral: contagens por disciplina e assunto de origem, formatos de questão, tamanho dos enunciados, presença de comando, tags HTML, estrutura da árvore por disciplina e nível, temas inativos, temas sem descrição, temas com zero questões no source.

Evidência das lixeiras: para os assuntos de origem mais frequentes, o que as questões realmente tratam, comparando `assunto_origem` com a decisão do pipeline.

Casos destacados, cada um com id e explicação: questões com disciplina fora do escopo; enunciados genéricos cujo conteúdo está nas alternativas; a questão com corrupção de OCR; questões que cobrem vários temas ao mesmo tempo; questões onde os dois modelos discordaram e por quê; temas duplicados na árvore e o efeito na classificação; a questão que cita um personagem chamado Gilson.

Gráficos poucos e úteis: distribuição de decisões, confiança por regra, precisão por faixa no corpus. Os achados alimentam a parte de diagnóstico do relatório.

## 13. API REST

`api/main.py` em FastAPI, reusando o pipeline, com três rotas. `POST /classificar` recebe `enunciado_html`, `comando` e `alternativas` e devolve decisão, tema central, extras, confiança, motivo e os três votos. `GET /temas` lista os temas ativos canônicos. `GET /saude` informa se Weaviate e cache estão disponíveis. Sem autenticação. É a peça que o relatório de produção aponta como encaixe no fluxo de importação.

## 14. Tela de revisão

`revisao-ui/` em Vite, React e TypeScript. Lê `publicacao.csv`, `questoes.jsonl` e os intermediários como arquivos estáticos. Mostra a fila de `revisar` com a questão, a sugestão, as justificativas dos dois modelos e os candidatos. O professor confirma ou troca o tema e exporta um CSV com as decisões dele. Estado só em memória. Sem backend. Não é publicada; roda local com `npm run dev`.

## 15. Cache, erros e reprodutibilidade

Toda chamada de modelo e de embedding é cacheada em `data/cache/` por hash do conteúdo e do modelo. O cache é commitado, então `uv run classificar` reproduz `publicacao.csv` sem chaves de API. Sem chave e sem cache para uma entrada, o pipeline falha com mensagem clara.

Falhas de API: até 3 retentativas com espera exponencial. Resposta que não passa na validação Pydantic: 1 retentativa; se persiste, voto inválido e regra 7. Weaviate indisponível: fallback em memória com aviso. Semente fixa em tudo que sorteia.

## 16. Testes

pytest em `tests/`, sem chamadas reais a modelos. Cobertura mínima: limpeza de HTML e montagem do texto de classificação; árvore de temas, incluindo pai, irmãos, ramo e canonicalização das duplicatas; regras de decisão com votos sintéticos para cada uma das 7 regras; reponderação, varredura de limiares e bootstrap da calibração com dados sintéticos; validação do formato de `publicacao.csv` e `previsao.txt`.

## 17. Entregáveis e documentação

- `publicacao.csv` e `previsao.txt` na raiz.
- `README.md` novo, com: o que é, como rodar em três comandos, o que gera cada arquivo, decisões manuais numeradas, modelos usados, custo e tempo reais. O README original da Vício vai para `docs/case/`.
- `relatorio/relatorio.md` com as quatro partes: como pensamos, diagnóstico, produção, e referência ao memo. Até 5 páginas.
- `relatorio/memo_professor.md`, 1 página, sem jargão de IA.
- `analise/` conforme seção 12.
- Histórico de commits por etapa.

## 18. Cronograma e linhas de corte

| Dia | Entrega | Corte se atrasar |
|---|---|---|
| Quarta 14 | Spec, plano, estrutura do repo, limpeza, índice, candidatos, planilha da âncora | Nenhum |
| Quinta 15 | Agentes coletam o corpus; dois modelos classificam as 359 e o corpus; âncora rotulada | Corpus cai para 3 questões por tema |
| Sexta 16 | Regras, calibração, `publicacao.csv`, `previsao.txt`, análise exploratória | Tela de revisão vira "faria com mais tempo" |
| Sábado 17 | API, tela, relatório, memo, README | API vira "faria com mais tempo" |
| Domingo 18 | Revisão final, repo público, envio | Folga |

## 19. Decisões registradas e riscos

1. Canonicalização dos 22 temas duplicados. Risco: se a equipe usou um id duplicado, a publicação no canônico conta como erro. Mitigação: duplicado vai em `extras_ids`; risco explicado no relatório.
2. Corpus coletado por agentes, não por código. Risco: viés para questões fáceis. Mitigação: reponderação por faixa e âncora.
3. Recuo ao pai em discordância entre irmãos. Risco: nenhum na régua; a Vício conta pai como certo.
4. Nunca publicar na raiz da disciplina. Seria tecnicamente "pai", mas inútil para o aluno.
5. Meta interna de 97% para ter margem sobre os 95%.
6. Cache commitado para reprodutibilidade sem chaves.

## 20. Custos estimados

Classificação das 359 por dois modelos, mais validação de até 1000 questões do corpus, mais embeddings: menos de 10 milhões de tokens no total, poucos dólares nos modelos de custo médio. Agentes de coleta consomem créditos de assinatura, não da API. Custos reais e tempo são registrados no README ao final.
