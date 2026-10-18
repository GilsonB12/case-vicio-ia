# Relatório: classificação de tópicos

Das 359 questões, publiquei **124 (35%)**, mandei **234** para revisão e marquei **1** como fora da árvore. Previsão de precisão nas publicadas, feita antes de qualquer checagem: **0,98**, intervalo **0,96 a 1,00** (`previsao.txt`). Uma auditoria cega por dois juízes independentes, feita depois, encontrou 96,0% e 99,2%. O código, os prompts, cada decisão tomada à mão, os intermediários e um livro-razão com tokens, latência e custo de cada uma das 1.953 chamadas estão no repositório; `uv run classificar tudo` reproduz `publicacao.csv` a partir do cache, sem chave de API, em 25 segundos.

**Custo das APIs nesta entrega.**

| | Chamadas | Anthropic (claude-sonnet-5-5) | OpenAI (gpt-5-mini + embeddings) | Total |
|---|---|---|---|---|
| Execução canônica (18/10), medida chamada a chamada pelo livro-razão | 1.953 | US$ 5,72 | US$ 0,87 | **US$ 6,58** |
| Primeira execução completa (16/10) e testes, pelo painel do provedor e pela medição por chamada | cerca de 1.520 | US$ 5,80 | cerca de US$ 0,90 | cerca de US$ 6,70 |
| **Projeto inteiro** | cerca de 3.500 | cerca de US$ 11,50 | cerca de US$ 1,80 | **cerca de US$ 13,30** |

Os avaliadores (rotuladores da âncora, checagem do corpus e auditoria) rodaram por assinatura, sem custo de API. Reproduzir pelo cache não custa nada.

## a) Como eu pensei

**O problema não é classificar bem; é saber quando estou certo.** A régua só pune erro nas publicadas. Um modelo de linguagem acerta "razoavelmente bem" sozinho, mas razoável não dá para publicar. Três decisões de desenho:

1. **Nenhum voto decide sozinho.** Dois modelos de fornecedores diferentes votam em separado sobre a mesma lista de candidatos, e um terceiro voto vem das questões parecidas num corpus de referência com tema conhecido. Publico quando concordam com confiança; discordância vai para o professor.
2. **A confiança vem dos dados, não da autodeclaração.** O que me diz quanto confiar é medir, num corpus com tema conhecido, quantas vezes cada combinação de regra de decisão e faixa de confiança acertou.
3. **Dúvida vai para a fila, não para o aluno.** Cobertura é o preço da precisão.

**Os dois modelos não são equivalentes, de propósito.** Um é o intermediário da Anthropic (claude-sonnet-5-5), o outro o pequeno da OpenAI (gpt-5-mini). Testei o intermediário da OpenAI: 25 vezes mais caro por voto, em tokens de raciocínio, para dar o mesmo voto. O segundo voto existe para dar independência, não paridade, e a calibração mede a dupla como ela é.

**Hipóteses que testei.**

- *Busca por similaridade reduz 351 temas a uma dúzia sem perder o certo.* Questões e temas viram vetores (embeddings da OpenAI) num banco vetorial (Weaviate); entram os 8 temas mais próximos, os temas das 10 questões vizinhas do corpus e os pais, até 12. Deu parcialmente: na âncora, o tema de referência estava na lista em 32 de 39. Os 7 que faltaram viraram o reparo descrito abaixo.
- *Concordância entre dois modelos independentes é o sinal mais forte que existe sem gabarito.* Confirmado, com uma condição. Os dois escolhem o mesmo tema em 72% das 359. No corpus, quando concordam com confiança mínima de 0,85 ou mais, acertam 99% (115 de 116); entre 0,80 e 0,85, 90% (44 de 49); abaixo de 0,80, 75%. Concordar não basta; concordar com confiança, sim.
- *Um corpus de questões reais, com tema conhecido, serve para calibrar.* Agentes de pesquisa buscaram, por tema da nossa árvore, questões em PDFs de bancas e bancos públicos, rotularam com o nosso tema pela regra de pai e filho, e o conjunto foi deduplicado contra as 359: 332 questões em 101 temas (`docs/projeto/coleta-corpus.md`). O pipeline rodou nelas como se fossem as 359, e a precisão por célula virou a previsão. Um leitor independente, às cegas, concordou com 88% dos rótulos do corpus.
- *A autodeclaração de confiança é informativa, mas comprimida.* Média de 0,80 no modelo pequeno e 0,71 no intermediário, que quase nunca passa de 0,85. Por isso ela entra em faixas cruzadas com a regra, nunca como número cru.

**O que descartei, e por quê.** *Rótulos de origem:* 7 das 8 questões com disciplina de origem de outra matéria são penais; decidir "fora" por esse campo erraria 7 em 8. *Detector de OCR:* a medida de palavras desconhecidas põe a Q0078, a única corrompida, em 12º lugar entre 359; virou lista de triagem. *Intervalo por bootstrap:* células pequenas todas certas davam intervalo zero; troquei por suavização de Jeffreys e simulação Beta. *Rotular a âncora eu mesmo:* sou desenvolvedor, não jurista; dois rotuladores independentes dos modelos do pipeline (Claude Fable 5.1, como agente com esforço de raciocínio extra alto, e Codex com gpt-6-astra, esforço alto, ambos por assinatura) rotularam 40 questões, concordaram em 34, e eu arbitrei as 6 restantes pelas justificativas e por pesquisa em sites de questões comentadas (`docs/projeto/ancora.md`). *Baixar o limiar para ganhar cobertura:* com 0,80 a cobertura iria a 48%, mas a precisão prevista cairia para 0,95 com limite inferior 0,92. O limiar ficou em 0,85, pela calibração, não à mão.

**O que mudei depois de ver os dados.** A primeira rodada deu 104 publicadas e 16 "fora". Das 16, 15 eram questões penais cujo tema existe na árvore (a Q0078 é Estatuto do Desarmamento), mas não estava na lista de candidatos; os modelos devolveram "nenhum candidato serve" e, na justificativa, disseram qual era o assunto. Usar essa justificativa como consulta ao índice recuperava o tema certo em primeiro lugar na maioria. Virou a etapa de **reparo**: a lista cresce e os dois modelos revotam. Resolveu 57 votos nulos e levou as "fora" a 1. A regra 6 também mudou: dois modelos sem tema numa questão penal vira "revisar", porque "fora" no case quer dizer outra disciplina.

**Duas rodadas completas.** Refiz tudo do zero para ter rastreabilidade de cada chamada, e a segunda rodada virou a canônica. Com os mesmos prompts, o intermediário repetiu o tema em 93% das questões, o pequeno em 82%. As decisões coincidiram em 85%; 94 questões foram publicadas nas duas vezes, todas no mesmo tema ou em pai e filho. O conjunto publicado muda nas bordas; a precisão, auditada nas duas rodadas, não.

**Como estimei a minha precisão.** No corpus, cada questão publicada cai numa célula (regra × faixa de confiança), e eu meço quantas acertaram pela régua, com suavização de Jeffreys. A precisão prevista para as 359 é a média das células onde as 359 publicadas caíram, o que corrige a diferença de mistura entre o corpus e as 359. O intervalo vem de 1.000 simulações. Os limiares saem de uma escada: tento média 0,97 com limite inferior 0,95 e relaxo um degrau por vez se não dá; nesta rodada o primeiro degrau foi atingido. A âncora confere: das 40, o pipeline publicou 13, e as 13 estão certas. O `previsao.txt` declara o que ainda pode deixar a previsão otimista: o corpus é mais fácil que as 359; seus rótulos vêm de modelos, não da equipe da Vício; os limiares foram escolhidos no mesmo corpus que mede a precisão; a âncora é pequena.

**A checagem externa.** Depois de fechar a previsão, os mesmos dois modelos da âncora, como juízes, sem ver decisão, voto nem candidato (prompts em `docs/projeto/prompts/`), classificaram às cegas as 124 publicadas. O juiz 1 concorda com 123 (99,2%, intervalo 96,3% a 99,9%) e o juiz 2 com 119 (96,0%, intervalo 91,3% a 98,4%). Os dois concordam entre si em 120, e nessas 120 o pipeline acerta 119. As cinco contestadas (`docs/projeto/auditoria-publicadas.md`) são nós sobrepostos da árvore ou questão mista, e uma (Q0202) é um crime narrado para cobrar erro de tipo. Com 124 questões, a auditoria não garante os 95% com 95% de confiança; mostra que a estimativa fica acima da régua pelos dois juízes e que os erros são de fronteira.

**Uma lição sobre o método.** Fazer isto sem coleção dourada e sem um especialista para calibrar é muito difícil. O julgamento, que o case diz que não se delega, ficou à mercê de modelos de IA, porque não havia a quem perguntar. Às cegas, a saída foi redundância: mais modelos, mais técnicas e mais checagens cruzadas do que o problema pediria em condições normais, para que o erro de um fosse pego pelo outro. Dois votantes, um corpus coletado só para medir, uma âncora, dois rotuladores, dois juízes. É caro e lento, e é o preço de não ter gabarito. Quando a fila do professor começar a produzir rótulos, a calibração passa a ter chão: dá para medir cada peça, descartar as que não pagam o que custam e, provavelmente, chegar a um modelo só, com menos técnicas, e resultado melhor. O desenho atual é o andaime; o prédio é o que fica depois.

## b) Diagnóstico

**Para quem o resultado foi bom.** Das 124 publicadas, 49 são de Penal, 33 de Processo Penal, 33 de Legislação Especial e 9 de Criminologia; 69 no tema de nível 1 e 55 em subtema; 96 trazem extras. Das 43 questões da lixeira "Concurso de Crimes", só 2 ficaram em Concurso de Crimes.

**Por que 65% ficou em revisão, e o que isso custa ao professor.** São 234 questões de 359. É muito para uma pessoa, e o case diz que o tempo do professor é escasso; mas publicar errado é o erro mais caro, e a calibração mostrou que publicar a faixa seguinte derrubaria a precisão prevista para 0,95 com limite inferior 0,92. A fila vem ordenada e agrupada por tema, com as confirmações rápidas primeiro:

| Por que foi para revisão | Questões | O que o revisor recebe |
|---|---|---|
| Os dois modelos concordam, mas a menor confiança fica abaixo de 0,85 | 158 | A sugestão dos dois, com justificativa. Na âncora, 18 de 19 estavam certas: confirmações rápidas. |
| Os dois modelos escolheram ramos diferentes | 51 | As duas opções e qual delas a vizinhança apoia. Na âncora, 1 de 6 certa: as difíceis de verdade. |
| Pai e filho, com confiança baixa para publicar no pai | 13 | O pai sugerido e os dois subtemas como extras. |
| Um ou os dois modelos não acharam tema que cubra a questão | 12 | O tema mais próximo do assunto que os modelos descreveram; questões mistas ou sem nó. |

Estimativa de esforço: meia hora para as 158 confirmações e cerca de duas horas para as 76 difíceis. Os 48 acordos com confiança entre 0,80 e 0,85 são os primeiros candidatos a sair da fila: os dois juízes auditaram essas 48 sugestões às cegas e cada um deu 46 certas (95,8%, intervalo 87% a 99%), 45 certas para os dois. É a régua no fio da navalha, como o corpus previa (90%); por isso ficam em revisão até os rótulos do professor confirmarem a faixa, e aí entram.

**O que nos dados atrapalha.** 20 questões têm enunciado genérico e o assunto só nas alternativas; 94 não têm comando; uma alternativa da Q0099 tem 35 mil caracteres de HTML do Word para 166 de texto; a Q0078 está corrompida por OCR, mas legível, e foi publicada no tema certo.

**O que nos temas atrapalha.** 20 temas duplicados sem descrição, 7 títulos com erro, 2 inativos. E nós sobrepostos em ramos diferentes: "Sentença" dentro de Procedimento Ordinário e "Sentença Penal"; "Conceitos e Espécies de Prisão" e "Prisões em Espécie"; "Abolitio Criminis" em Punibilidade e "Lei penal no Tempo"; desaforamento, que é do júri e é modificação de competência. Pela régua, publicar em um quando a equipe marcou o outro conta como erro. Esse padrão apareceu nas três checagens: na âncora, no corpus (4 das 7 divergências) e na auditoria (4 das 5 contestadas).

**Que tipo de questão é difícil.** *Mista:* a Q0282 tem duas alternativas de Lei Maria da Penha, duas do Estatuto do Desarmamento e uma de racismo; não há tema que a represente. *Enquadramento entre irmãos:* "isso é furto, roubo ou extorsão?", o erro mais provável é o irmão, que a régua conta como erro. *Conteúdo sem nó:* a "pendura" (Q0106) é o art. 176 do Código Penal, sem tema na árvore. *Crime narrado para cobrar a parte geral:* a Q0202 conta um caso do art. 218-B para perguntar sobre erro de tipo. *Fronteira entre ramos:* a Q0180 é busca domiciliar sem mandado, "Busca e Apreensão" ou "Prova Ilícita". Em comum: dois especialistas humanos também discordariam, e a resposta certa do sistema é revisar.

**Um beco sem saída.** Questão com questão sempre parece muito (similaridade 0,70 a 0,76), porque as duas têm forma de prova; questão com descrição de tema parece menos, mesmo no mesmo assunto. Na Q0001, sobre Tribunal do Júri, uma questão do corpus sobre Ilicitude apareceu com similaridade maior que o próprio tema do Júri. Por isso a similaridade só monta a lista e nunca decide, e por isso o voto por vizinhança quase nunca contradiz os modelos com força. Com uma base rotulada grande ele fica forte; com 332 questões é fraco, e eu o tratei como tal.

## c) Produção

**Para 50 mil questões por semana, mais as importações novas:**

1. **Importação** limpa o texto, remove duplicatas por embedding e guarda a proveniência.
2. **Embeddings com cache**, recalculados só quando o texto muda.
3. **Busca de candidatos híbrida**: similaridade mais busca por número de lei e por título do tema. A busca só por similaridade perdeu o tema certo em 18% da âncora; é o ponto mais barato de melhorar.
4. **Votação em cascata.** O modelo pequeno vota em tudo; o intermediário só entra quando o pequeno hesita ou a vizinhança discorda. Os dados apoiam: o pequeno é a fonte de ruído, o intermediário é quem segura a precisão.
5. **Terceiro voto pela base rotulada**, que cresce sozinha: cada decisão do professor vira rótulo. Com alguns milhares, um classificador treinado sobre os embeddings substitui a vizinhança e sai mais barato que qualquer modelo de linguagem.
6. **Regras calibradas** como as deste case, recalibradas a cada mês.
7. **Fila de revisão** por tema, com sugestão e justificativa. A tela deste repositório é o protótipo.
8. **Agentes só fora do caminho da questão:** coletar corpus, auditar a árvore, investigar uma lixeira.

**Custo por questão, medido chamada a chamada.** O intermediário recebe em média 3.015 tokens e devolve 156, em 2,2 segundos, a US$ 0,0076 por voto; o pequeno recebe 1.599 e devolve 357, dos quais 252 de raciocínio, em 3,5 segundos, a US$ 0,0011. Votação dupla em tudo: cerca de US$ 0,010 por questão, US$ 500 por semana. Em cascata, com o intermediário em um terço das questões: cerca de US$ 0,004, US$ 200 por semana. Reprocessar só o que é novo derruba isso para uma fração.

**Como eu mediria a qualidade continuamente.** Auditoria amostral semanal das publicadas por um professor, a única medida que a régua respeita; a taxa de aceite da sugestão na fila, que mede a qualidade das sugestões, e a taxa de "fora", que mede buracos na árvore; reportes de alunos por tema, que viram alerta de lixeira e devolvem a questão à fila; deriva de regras, confiança, tokens e latência por semana, direto do livro-razão; recalibração mensal dos limiares e um painel com cobertura, precisão auditada, fila e custo.

## d) Memo para o professor

**O que eu encontrei nos temas.**

- 20 temas duplicados, sem descrição, numerados de 6716 a 6738. "Lei Maria da Penha" existe em Penal e em Legislação Especial, e as questões dela podem ficar divididas. Tratei cada duplicado como o original.
- 7 títulos com erro de digitação: "Escolas Crimonológicas" (4373), "Estaturo do Idoso" (4696) e outros cinco. O aluno vê esses títulos, e a busca por "Estatuto" pode não achar o tema.
- 2 temas inativos (Direito penal econômico; Tratados e convenções), 7 temas sem nenhuma questão, uma descrição com uma palavra em árabe (Procedimento Ordinário, 5530).
- Pares de temas que cobrem o mesmo assunto em ramos diferentes: Sentença em Procedimento Ordinário e Sentença Penal; Conceitos e Espécies de Prisão e Prisões em Espécie; Abolitio Criminis em Punibilidade e Lei penal no Tempo; Denúncia em Ação Penal e Oferecimento da Peça Acusatória em Procedimento Ordinário. Quem classifica, pessoa ou máquina, erra pela régua em metade desses casos, porque não há como saber qual dos dois a equipe prefere.
- Lixeiras confirmadas: "Concurso de Crimes" tem 43 questões na origem e quase nenhuma é sobre concurso de crimes. "Ação Penal (Parte 02)" mistura recurso, prisão, organizações criminosas e prescrição.

**O que eu recomendo mudar nos temas.**

- Fundir ou aposentar os 20 duplicados e corrigir os 7 títulos, a começar pelo 4696, que é o id que fica.
- Para cada par de temas sobrepostos, decidir qual recebe as questões, ou fundir.
- Fixar três convenções: se "Estelionato" cobre o capítulo todo (inclusive a "pendura", art. 176) ou só o art. 171; onde entra uma questão que mistura várias leis especiais; e se uma questão que narra um crime para cobrar um instituto da parte geral vai para o crime ou para o instituto.
- Criar nó para conteúdo frequente sem lugar, quando a fila mostrar o mesmo buraco repetidas vezes.

**Do que eu preciso do senhor.**

- Cerca de duas horas e meia na fila de revisão deste lote: 234 questões, agrupadas por tema, com as 158 confirmações rápidas primeiro. A tela mostra a questão, a sugestão e a justificativa; basta confirmar, trocar ou marcar fora.
- Uma leitura dos 6 casos em que os rotuladores da âncora divergiram (`docs/projeto/ancora.md`) e dos 5 que a auditoria contestou (`docs/projeto/auditoria-publicadas.md`): são as convenções acima, encarnadas em questões reais.
- Uma amostra mensal de 50 questões publicadas para auditoria. É isso que vai dizer se os 95% estão de pé, e é o que nenhum modelo pode fazer pelo senhor.
