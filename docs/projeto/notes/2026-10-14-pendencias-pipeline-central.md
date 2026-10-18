# Pendências e decisões do plano pipeline-central (2026-10-14)

Registro das decisões tomadas durante a implementação e dos itens deixados para os próximos planos (corpus, análise exploratória, API, tela e relatório). Serve também de entrada para a seção de limitações do relatório.

## Decisões de projeto

- Branch único `pipeline-central` no diretório principal, mergeado em `main` ao final; histórico por etapa.
- Versões de biblioteca resolvidas pelo uv (pandas 3, LangChain 1, weaviate-client 4.23) sem pinar para baixo; a spec só fixa pisos.
- Limpeza de HTML remove também os literais `\n` e `\t` que vêm do banco.
- O protocolo `Indice` ganhou `fechar()`; os índices são fechados em `finally`, inclusive quando a carga falha.
- Inserção no Weaviate usa vetor nomeado (`{"default": vetor}`), porque `self_provided()` cria vetor nomeado; validado contra o servidor 1.27.0.
- O modelo da Anthropic não aceita `temperature` fora do padrão nem `tool_choice` forçado; a saída estruturada usa `json_schema`, esforço de raciocínio baixo e `max_tokens` 4096.
- Extras só recebem os dois temas escolhidos na regra 3 (spec §8); nas demais regras, a união dos extras dos votos.
- Confiança da regra 5 é o mínimo dos dois votos.
- Calibração: precisão por célula (regra × faixa) com suavização de Jeffreys, recuo para a faixa com menos de 5 questões do corpus e depois para o global; intervalo por simulação da posterior Beta por célula; o método de bootstrap por reamostragem colapsava em células pequenas todas certas.
- `alvo_atingido` é calculado com os números finais (1000 amostras); o `previsao.txt` diz qual degrau da escada de seleção foi usado e declara o viés de escolher limiares no mesmo corpus que estima a precisão.
- Escada de seleção dos limiares: degrau 0 média ≥ 0.97 e limite inferior ≥ 0.95; degrau 1 só o limite inferior; degrau 2 só a média; degrau 3 maior limite inferior. A régua do cliente é o piso de 95%; a média 0.97 é margem interna.
- Erros 4xx dos provedores (exceto 429) param na hora; erro de schema tem uma retentativa; disjuntor após 5 falhas seguidas do mesmo provedor.
- A chave do cache dos votos inclui a configuração da chamada (esforço, max_tokens, método).
- `classificar tudo` reaproveita intermediários existentes e só recalcula com `--recalcular`; os intermediários e o cache commitados são o caminho de reprodução sem chaves.
- A planilha da âncora nunca é sobrescrita quando já tem rótulos; é gravada em UTF-8 com BOM para o Excel; a leitura aceita `;` como separador.
- A heurística de OCR da spec §5 fica para a análise exploratória.

## Itens adiados para os próximos planos

- Testes: ambiguidade na canonicalização deve levantar `ValueError`; teste de `documento()` mais forte; validação em código da tabela de exceções canônicas; testes de passada 2 e alvo corpus em `rodar_candidatos`; denominador do `peso_nivel2`; vizinho não publicável e clamp de similaridade; `rodar_ancora` e truncamento de 200 caracteres; `etapa_publicar`; `carregar_limiares`; `verificar_provedores`.
- Robustez: `embed_documents` aceita bool/NaN no cache; escrita de cache não atômica; `USAR_WEAVIATE` com valor desconhecido age como `auto`; URL sem esquema; `tamanho()` chamado duas vezes por questão no Weaviate; corpus carregado duas vezes em `alvo=corpus`; `carregar_corpus` com arquivo vazio levanta `KeyError`; validador do CSV assume células de texto e trunca listas de ids em 10; nome de modelo com `:` como pasta.
- Decisão: `decidir` por si só não impede tema não publicável (o validador do CSV e `rodar_decisoes` impedem); motivo da regra 3 chama pai e filho de "irmãos"; regra 5 reporta só a contradição quando as duas causas valem.
- Calibração: os sorteios por unidade são independentes e ignoram a covariância quando células pequenas recuam para a mesma faixa (intervalo até ~1/√2 mais estreito nesse caso); a frase do alargamento repete o limite inferior quando só o superior moveu; `alvo_atingido` é julgado antes do alargamento pela âncora.
- Planilha ilegível é recusada com a mensagem de "já tem rótulos"; `carregar_ancora_manual` ainda não lê cp1252, então a âncora deve ser salva como CSV UTF-8.
- Chamadas aos modelos são sequenciais (1 a 3 horas estimadas para 359 questões mais o corpus); um pool de 4 a 8 threads seria seguro, porque há um arquivo de cache por chamada.

## Antes da execução real

- Rodar `classificar votos --verificar` e `classificar votos --limite 5` nos dois provedores.
- Execução canônica com Weaviate via Docker; commitar intermediários e cache.
- O piso de 0.95 no limite inferior exige cerca de 60 publicações todas certas numa célula; um corpus com só 3 questões por tema tornaria a estimativa por célula quase inútil.

## Formas de a previsão ainda ser otimista, a declarar no relatório

- Deslocamento de dificuldade dentro da célula entre o corpus e as 359.
- Rótulos do corpus vêm de coleta por nome de tema, da mesma natureza dos modelos que votam.
- Quase-duplicatas internas do corpus vazando pelo leave-one-out.
- Confiança dos modelos concentrada em 0.85 a 0.95, o que reduz as 5 faixas a 2 na prática.
- Escolha dos limiares no mesmo corpus da estimativa.
- Âncora pequena, que só detecta diferenças grandes.

## Plano da análise exploratória (2026-10-15)

### Decisões

- A heurística de OCR é tratada como lista de triagem ordenada, não como detector; o notebook e o achados.md dizem isso.
- achados.md ficou com cerca de 3,5 páginas; o limite de 3 era indicativo e o conteúdo extra é a lista de correções na fonte, que o memo precisa.

### Itens adiados

Task 1: minor (deferred): allow-list de pontuação estreita; tema.ativo com NA; chave de enunciado repetido não tira pontuação final.
Task 2: minor (deferred): ticks do histograma sem separador de milhar pt-BR; gráficos 1-3 sem título do eixo de valor (rótulos diretos).
Task 3: minor (deferred): termos ainda sem glosa ("prompt" antes da seção 5, "ids", "HTML do Word", "corpus de referência").

- A heurística de OCR (proporção de palavras fora do vocabulário) não isola a questão corrompida: Q0078 fica em 12º. Registrar no relatório como beco sem saída e como lista de triagem.

## Plano da API e da tela de revisão (2026-10-15)

### Itens adiados

Task 1: minor (deferred): nomes de coleção Weaviate colidem com o pipeline em lote (prefixo "Api" via criar=); dublê sem fechar(); /saude abre conexão a cada chamada; enunciado vazio aceito.
Task 2: minor (deferred): observação sem decisão fica fora do CSV exportado apesar do placeholder; desfazer rearma o aviso de fechar aba; CSV exportado sem BOM para Excel; copiar-dados não apaga cópia antiga; status comparado com caixa; EX05 motivo não segue o template; DOMParser a cada tecla.

- Nomes de coleção no Weaviate são compartilhados entre a API e o pipeline em lote (`Tema`, `CorpusQuestao`); não rodar os dois ao mesmo tempo contra o mesmo Weaviate, ou prefixar as coleções da API.

## Execução real (16/10/2026)

### Números

- Corpus consolidado: 362 coletadas, 332 mantidas em 101 temas (10 curtas, 13 duplicatas de texto, 7 iguais a questões do case); fonte alta em 278, média em 54.
- Votos: 359 + 332 questões, dois modelos cada, sem nenhuma falha de provedor; 80 minutos; concordância exata entre os modelos em 70% das 359 e 78% do corpus.
- Primeira decisão: 104 publicadas (29%), 239 revisar, 16 fora; precisão prevista 0,97 [0,94; 1,00]; âncora 9 de 9 publicadas certas.
- Depois do reparo de candidatos e da regra 6 corrigida: 117 publicadas (33%), 241 revisar, 1 fora (a Q0142, de Direito Tributário); precisão prevista 0,97 [0,94; 1,00]; âncora 11 de 11 publicadas certas.
- Custo aproximado da execução: US$ 6,3 no provedor principal e US$ 0,8 no secundário, incluindo embeddings e o reparo (122 chamadas a mais). `classificar tudo` reproduz `publicacao.csv` e `previsao.txt` idênticos a partir do cache, sem nenhuma chamada, em 25 segundos.

### Decisões tomadas depois de ver os dados

- Limiar de publicação 0,85 mantido pela escada de seleção: no corpus, acordos com confiança mínima entre 0,80 e 0,85 acertam 90%; de 0,85 para cima, 98%. Baixar o limiar para 0,80 daria 39% de cobertura com precisão prevista 0,95 e limite inferior 0,92, abaixo da régua.
- Reparo de candidatos (`classificar reparar`): a busca por similaridade deixou o tema certo fora da lista em 7 das 39 questões da âncora com tema, e 15 das 16 decisões `fora` eram questões dentro da árvore cujo tema não tinha sido oferecido. A justificativa do voto nulo vira consulta ao índice; os dois modelos revotam sobre a lista ampliada. Nas 359, 49 questões revotadas e 57 votos nulos resolvidos; no corpus, 12 e 15.
- Regra 6: os dois modelos sem tema numa questão das quatro disciplinas vira `revisar` com sugestão (o tema mais próximo do assunto descrito), não `fora`. `fora` fica só para a regra 1.
- Âncora: 34 das 40 com rótulo idêntico pelos dois rotuladores; nas 6 restantes a arbitragem está em `docs/projeto/ancora.md`. Nas 40, as sugestões em `revisar` pela regra 5 acertaram 16 de 17; pela regra 4 (modelos em ramos diferentes), 0 de 6: divergência de ramo é sinal de questão difícil de verdade.

### Para o relatório

- Cobertura de 33% é o preço da régua com os modelos escolhidos: a autodeclaração de confiança dos modelos é comprimida e o segundo modelo é conservador, o que empurra 161 acordos para `revisar` pela regra 5.
- A busca de candidatos é o ponto fraco mais barato de melhorar: busca híbrida por número de lei e por título, ou lista maior, antes de qualquer troca de modelo.

### Fechamento (17/10/2026)

- Livro-razão de custos: cada chamada de modelo ou de embeddings grava uma linha em `data/custos/chamadas.jsonl`, com tokens, latência, custo pela tabela de `src/classificador/precos.json` e origem (api ou cache); `classificar custos` agrega. As 1.504 chamadas da execução canônica são anteriores ao livro, por isso o custo delas vem do painel do provedor (US$ 5,80 na Anthropic) e da medição por chamada. O livro commitado é o da reprodução pelo cache: 1.504 linhas, custo zero.
- Reprodução sem chaves comprovada com `.env.example`: `classificar tudo` reproduz `publicacao.csv` e `previsao.txt` byte a byte, sem nenhuma chamada. Para isso o reparo passou a reaproveitar a lista ampliada já gravada: com o Weaviate parado, o índice em memória difere na quarta casa decimal e mudava um candidato de empate na Q0010, o que gerava um prompt novo e uma chamada paga. O modelo padrão da OpenAI passou a ser o da execução canônica (`gpt-5-mini`), para o `tudo` funcionar mesmo sem `.env`.
- Checagem independente de 60 rótulos do corpus: 88% compatíveis pela régua; detalhes em `docs/projeto/coleta-corpus.md`.
- Risco que sobra: questão elegível ao reparo que não ganhou tema novo na primeira vez não tem lista gravada e ainda consulta o índice na reprodução; não ocorreu nesta execução (todas as 61 elegíveis foram revotadas).

## Rodada 2, canônica (18/10/2026)

- Refeita do zero com o livro-razão ligado e o Weaviate de pé, para ter rastreabilidade de todas as inferências: 1.953 chamadas (753 por modelo e 447 lotes de embeddings), nenhuma falha, 79 minutos. Custo pelo livro: US$ 6,58 (Anthropic 5,72; OpenAI 0,84; embeddings 0,03). O painel da Anthropic da rodada 1 marcou US$ 5,80, 1,4% acima do calculado para a rodada 2.
- Resultado: 124 publicadas (35%), 234 revisar, 1 fora; precisão prevista 0,98 [0,96; 1,00]; limiares 0,85 no tema e 0,55 no pai, escolhidos pelo primeiro degrau da escada (meta inteira atingida); âncora 13 de 13 publicadas certas.
- Estabilidade entre rodadas: mesma decisão em 306 de 359 (85%); 94 publicadas em comum, todas compatíveis pela régua; 30 só na rodada 2, 23 só na 1; tema decidido ou sugerido compatível em 324 de 358. Por modelo: Anthropic mesmo tema em 93% (confiança varia 0,04 em média), OpenAI em 82% (varia 0,08). O modelo pequeno é a fonte principal de ruído; isso reforça a cascata em produção.
- Por chamada: Anthropic 3.015 tokens de entrada, 156 de saída, 2,2 s de média e 2,9 s no percentil 95; OpenAI 1.599 de entrada, 357 de saída (252 de raciocínio), 3,5 s de média e 6,3 s no percentil 95. O custo do modelo da Anthropic é quase todo entrada (schema estruturado contado como entrada); o da OpenAI é quase todo raciocínio.
- A rodada 1 (16/10) está preservada fora do repositório para comparação; o que fica no repositório é a rodada 2.
