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
