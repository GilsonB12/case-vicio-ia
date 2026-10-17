# Relatório: classificação de tópicos

Das 359 questões, publiquei **117 (33%)**, mandei **241** para revisão e marquei **1** como fora da árvore. Previsão de precisão nas publicadas: **0,97**, intervalo **0,94 a 1,00** (`previsao.txt`). A seguir: como pensei, o que atrapalha, como eu levaria isto para produção e um memo para o professor. O código, os prompts, cada decisão tomada à mão e os arquivos intermediários estão no repositório; `uv run classificar tudo` reproduz `publicacao.csv` a partir do cache, sem chave de API, em 25 segundos.

## a) Como eu pensei

**O problema não é classificar bem; é saber quando estou certo.** A régua só pune erro nas publicadas. Um modelo de linguagem acerta "razoavelmente bem" sozinho, mas razoável não dá para publicar. O desenho inteiro gira em torno de três decisões:

1. **Nenhum voto decide sozinho.** Dois modelos de fornecedores diferentes (claude-sonnet-5-5 e gpt-5-mini) votam em separado sobre a mesma lista de candidatos, e um terceiro voto vem das questões parecidas num corpus de referência com tema conhecido. Publico quando concordam com confiança; discordância vai para o professor.
2. **A confiança vem dos dados, não da autodeclaração.** O modelo diz "0,9", mas o que me diz quanto confiar é medir, num corpus com tema conhecido, quantas vezes cada combinação de regra de decisão e faixa de confiança acertou.
3. **Dúvida vai para a fila, não para o aluno.** Cobertura é o preço da precisão.

**Hipóteses que testei, e o que deu.**

- *Busca por similaridade reduz 351 temas a uma dúzia sem perder o certo.* Cada questão e cada tema viram vetores (embeddings da OpenAI, text-embedding-3-large) guardados num banco vetorial (Weaviate); para cada questão entram os 8 temas mais próximos, os temas das 10 questões vizinhas do corpus e os pais, até 12. Deu parcialmente: na âncora, o tema de referência estava entre os candidatos em 32 de 39 questões. Os 7 que faltaram viraram o reparo descrito abaixo.
- *Concordância entre dois modelos independentes é o sinal mais forte que existe sem gabarito.* Confirmado, com uma condição. Os dois escolhem o mesmo tema em 71% das 359. No corpus, quando concordam com confiança mínima de 0,85 ou mais, acertam 98% (111 de 113); entre 0,80 e 0,85, 90% (43 de 48); abaixo de 0,80, 77% (72 de 93). Concordar não basta; concordar com confiança, sim.
- *Um corpus de questões reais, com tema conhecido, serve para calibrar.* Coletei 332 questões em 101 temas, de PDFs de bancas e bancos públicos de questões, com proveniência registrada (`docs/projeto/coleta-corpus.md`). O pipeline rodou nelas como se fossem as 359, e eu medi a precisão por célula (regra × faixa de confiança).
- *A autodeclaração de confiança é informativa, mas comprimida.* Confirmado: a média é 0,79 num modelo e 0,71 no outro, e o segundo quase nunca passa de 0,85. Por isso a confiança entra em faixas cruzadas com a regra, nunca como número cru.

**O que descartei, e por quê.**

- *Usar os rótulos de origem.* Das 8 questões cuja disciplina de origem é de outra matéria, 7 são penais. Decidir "fora" por esse campo erraria 7 em 8. Os rótulos de origem ficaram fora do prompt e da busca.
- *Detector de texto corrompido por OCR.* A medida de palavras desconhecidas põe a Q0078, a única visivelmente corrompida, em 12º lugar entre 359, atrás de 11 questões limpas com vocabulário raro. Virou lista de triagem para leitura humana.
- *Intervalo por bootstrap.* Reamostrar células pequenas em que tudo acertou dá intervalo zero, uma certeza falsa. Troquei por suavização de Jeffreys e simulação da distribuição Beta de cada célula.
- *Modelo maior no segundo voto.* Gastou 25 vezes mais, em tokens de raciocínio, para dar o mesmo voto no teste. Fiquei com o modelo pequeno.
- *Rotular a âncora eu mesmo.* Sou desenvolvedor, não jurista. Dois rotuladores independentes, fortes e em configuração distinta da do pipeline, propuseram rótulos; concordaram em 34 das 40; eu arbitrei as 6 restantes pelas justificativas e por pesquisa em sites de questões comentadas. Regras e decisões em `docs/projeto/ancora.md`.
- *Baixar o limiar de publicação para ganhar cobertura.* Com limiar 0,80 a cobertura iria a cerca de 39%, mas a precisão prevista cairia para 0,95 com limite inferior 0,92. Abaixo da régua. O limiar ficou em 0,85, escolhido pela calibração, não à mão.

**O que mudei depois de ver os dados.** A primeira rodada deu 104 publicadas e 16 "fora". Olhando as 16, 15 eram questões penais cujo tema existe na árvore (a Q0078 é Estatuto do Desarmamento), mas não estava na lista de candidatos; os dois modelos devolveram "nenhum candidato serve" e, na justificativa, disseram qual era o assunto. Testei usar essa justificativa como consulta ao índice de temas: recuperava o tema certo em primeiro lugar na maioria. Virou a etapa de **reparo**: a lista cresce com os temas recuperados e os dois modelos revotam. Custou US$ 0,55, revotou 49 questões, resolveu 57 votos nulos e levou as publicadas a 117 e as "fora" a 1. A regra 6 também mudou: dois modelos sem tema numa questão penal vira "revisar", porque "fora" no case quer dizer outra disciplina.

**Como estimei a minha precisão.** No corpus, cada questão publicada cai numa célula (regra × faixa de confiança), e eu meço quantas acertaram pela régua (igual, pai ou filho), com suavização de Jeffreys para células pequenas. A precisão prevista para as 359 é a média das células onde as 359 publicadas caíram, o que corrige a diferença de mistura entre o corpus e as 359. O intervalo vem de 1.000 simulações. Os limiares saem de uma escada: tento média 0,97 com limite inferior 0,95; se não dá, relaxo um degrau por vez, e o `previsao.txt` diz qual degrau foi usado. A âncora confere: das 40, o pipeline publicou 11, e as 11 estão certas (previsto 0,97). O `previsao.txt` declara o que ainda pode deixar a previsão otimista: o corpus é mais fácil que as 359; seus rótulos vêm de modelos lendo questões, não da equipe da Vício; os limiares foram escolhidos no mesmo corpus que mede a precisão; a âncora é pequena.

## b) Diagnóstico

**Para quem o resultado foi bom.** Das 117 publicadas, 53 são de Penal, 28 de Legislação Especial, 27 de Processo Penal e 9 de Criminologia; 63 no tema de nível 1 e 54 em subtema; 88 trazem extras. Das 43 questões da lixeira "Concurso de Crimes", nenhuma foi para Concurso de Crimes: 17 publicadas em Crimes contra o Patrimônio, contra a Administração Pública, Tráfico de Drogas e outros, 26 em revisão.

**Por que 67% ficou em revisão.** 161 questões são acordos dos dois modelos abaixo da confiança 0,85 (39 delas entre 0,80 e 0,85); 56 são divergências de ramo; 14 são pai e filho com confiança baixa; 10 são questões em que um ou os dois modelos não acharam tema. O gargalo é a cautela do segundo modelo, não a discordância. Na âncora, as sugestões dos acordos de confiança baixa acertaram 16 de 17; as sugestões das divergências de ramo acertaram 0 de 6. Divergência de ramo é sinal de questão difícil de verdade; acordo cauteloso é, em geral, acerto que não ousei publicar.

**O que nos dados atrapalha.** 20 questões têm enunciado genérico ("Assinale a alternativa correta") e o assunto só nas alternativas; o pipeline lê as alternativas inteiras, mas é por isso que o prompt insiste nelas. 94 não têm comando. Uma alternativa da Q0099 tem 35 mil caracteres de HTML do Word para 166 de texto. A Q0078 está corrompida por OCR, mas legível, e foi publicada no tema certo.

**O que nos temas atrapalha.** 20 temas duplicados sem descrição (a mesma Lei Maria da Penha em Penal e em Legislação Especial), 7 títulos com erro, 2 inativos. E nós sobrepostos em ramos diferentes: "Sentença" dentro de Procedimento Ordinário e "Sentença Penal" como tema; "Conceitos e Espécies de Prisão" e "Prisões em Espécie"; "Denúncia" em Ação Penal e "Oferecimento da Peça Acusatória" em Procedimento Ordinário. Pela régua, publicar em um quando a equipe marcou o outro conta como erro. Medi quanto isso pesa: um leitor independente rotulou às cegas 60 questões do corpus e concordou com o rótulo em 88% pela régua; das 7 divergências, 4 são exatamente esses nós sobrepostos. Das 139 questões do corpus que o pipeline publicou, errou 2, e as duas são casos assim.

**Que tipo de questão é difícil, e por quê.**

- *Questão mista.* A Q0282 tem duas alternativas de Lei Maria da Penha, duas do Estatuto do Desarmamento e uma de racismo. Não há tema que a represente; o certo é tema central mais extras, e qual é o central é convenção, não conhecimento.
- *Enquadramento entre irmãos.* "Isso é furto, roubo ou extorsão?" O erro mais provável é o irmão, que a régua conta como erro. É o tipo mais perigoso de publicar.
- *Conteúdo sem nó.* A "pendura" (Q0106) é o art. 176 do Código Penal, sem tema na árvore; cai no pai. Toda árvore tem buracos, e o sistema precisa saber subir.
- *Fronteira entre ramos.* A Q0180 é busca domiciliar sem mandado: "Busca e Apreensão" ou "Prova Ilícita"? Dois leitores competentes divergiram, e os dois têm razão.
- *Lei revogada.* A Q0163 cita a antiga Lei de Abuso de Autoridade. O tema continua; a lei, não.

Em comum: são questões em que dois especialistas humanos também discordariam. Nelas a resposta certa do sistema é revisar, e é para lá que ele as manda.

**Um beco sem saída que vale registrar.** Questão com questão sempre parece muito (similaridade 0,70 a 0,76), porque as duas têm forma de prova; questão com descrição de tema parece menos, mesmo quando o assunto é o mesmo. Na Q0001, sobre Tribunal do Júri, uma questão do corpus sobre Ilicitude apareceu com similaridade maior que o próprio tema do Júri. Por isso a similaridade só monta a lista e nunca decide, e por isso o voto por vizinhança quase nunca contradiz os modelos com força. Em produção, com uma base rotulada grande, esse voto fica forte; com 332 questões, ele é fraco e eu o tratei como tal.

## c) Produção

**O cenário:** 50 mil questões por semana, mais as importações novas.

1. **Importação** limpa o texto, remove duplicatas por embedding e guarda a proveniência.
2. **Embeddings com cache** para cada questão e cada tema, recalculados só quando o texto muda. É o passo mais barato e o que mais reaproveita.
3. **Busca de candidatos** num banco vetorial, híbrida: similaridade mais busca por número de lei e por título do tema. A busca só por similaridade perdeu o tema certo em 18% da âncora; esse é o ponto mais barato de melhorar, antes de qualquer troca de modelo.
4. **Votação em cascata.** O modelo pequeno vota primeiro; o maior só entra quando o pequeno tem confiança baixa ou a vizinhança discorda. Corta a maior parte do custo sem perder as publicações fáceis.
5. **Terceiro voto pela base rotulada**, que cresce sozinha: cada decisão do professor na fila vira rótulo. Com alguns milhares de rótulos, um classificador treinado sobre os embeddings substitui o voto por vizinhança e sai mais barato que qualquer modelo de linguagem.
6. **Regras calibradas** como as deste case, recalibradas a cada mês com os rótulos novos.
7. **Fila de revisão** por tema, com sugestão e justificativa de cada voto. A tela deste repositório é o protótipo.
8. **Agentes só fora do caminho da questão:** coletar corpus, auditar a árvore, investigar uma lixeira. No fluxo por questão, nada de agente: previsibilidade e custo mandam.

**Custo por questão.** Medido neste case: US$ 0,0077 por chamada do modelo principal (US$ 5,80 no painel do provedor para 752 chamadas), US$ 0,001 do secundário, embeddings em centavos. Votação dupla em tudo: cerca de US$ 0,009 por questão, US$ 450 por semana para 50 mil. Em cascata, com o modelo maior em um terço das questões: cerca de US$ 0,0035, US$ 175 por semana. Reprocessar só o que é novo derruba isso para uma fração. Para rastrear, cada chamada de modelo grava uma linha num livro-razão (tokens de entrada, saída e raciocínio, latência, custo pela tabela de preços versionada), e `classificar custos` agrega por execução, etapa e modelo.

**Como eu mediria a qualidade continuamente.**

- *Auditoria amostral das publicadas*, toda semana, por um professor. É a única medida que a régua respeita.
- *Fila de revisão como termômetro:* a taxa de aceite da sugestão mede a qualidade das sugestões; a taxa de "fora" mede buracos na árvore.
- *Reportes de alunos por tema:* tema com índice acima da linha de base vira alerta de lixeira, e as questões dele voltam para a fila com o reporte anexado.
- *Deriva:* distribuição de regras e de confiança por semana comparada à linha de base; mudança brusca indica importação diferente ou mudança de modelo.
- *Recalibração mensal* dos limiares com os rótulos acumulados, e um painel com cobertura, precisão auditada, tamanho da fila e custo.

## d) Memo para o professor

**O que eu encontrei nos temas.**

- 20 temas duplicados, sem descrição, numerados de 6716 a 6738. "Lei Maria da Penha" existe em Penal e em Legislação Especial, e as questões dela podem ficar divididas. Tratei cada duplicado como o original.
- 7 títulos com erro de digitação: "Escolas Crimonológicas" (4373), "Estaturo do Idoso" (4696) e outros cinco. O aluno vê esses títulos, e a busca por "Estatuto" pode não achar o tema.
- 2 temas inativos (Direito penal econômico; Tratados e convenções), 7 temas sem nenhuma questão, uma descrição com uma palavra em árabe (Procedimento Ordinário, 5530).
- Pares de temas que cobrem o mesmo assunto em ramos diferentes: Sentença em Procedimento Ordinário e Sentença Penal; Conceitos e Espécies de Prisão e Prisões em Espécie; Denúncia em Ação Penal e Oferecimento da Peça Acusatória em Procedimento Ordinário. Quem classifica, pessoa ou máquina, erra pela régua em metade desses casos, porque não há como saber qual dos dois a equipe prefere.
- Lixeiras confirmadas: "Concurso de Crimes" tem 43 questões na origem e nenhuma delas é sobre concurso de crimes. "Ação Penal (Parte 02)" mistura recurso, prisão, organizações criminosas e prescrição.

**O que eu recomendo mudar nos temas.**

- Fundir ou aposentar os 20 duplicados e corrigir os 7 títulos, a começar pelo 4696, que é o id que fica.
- Para cada par de temas sobrepostos, decidir qual recebe as questões, ou fundir.
- Fixar três convenções que hoje ficam ao gosto de quem classifica: se "Estelionato" cobre o capítulo todo (inclusive a "pendura", art. 176) ou só o art. 171; onde entra uma questão que mistura várias leis especiais; e se temas introdutórios ("Princípios", "Conceito e Fontes") recebem questões ou só organizam.
- Criar nó para conteúdo frequente sem lugar, quando a fila mostrar o mesmo buraco repetidas vezes.

**Do que eu preciso do senhor.**

- Cerca de duas horas por semana na fila de revisão, começando pelas 241 questões deste lote, agrupadas por tema. A tela mostra a questão, a sugestão e a justificativa; basta confirmar, trocar ou marcar fora. As 161 sugestões de "acordo com confiança baixa" devem ser rápidas: na amostra que conferi, 16 em 17 estavam certas.
- Uma leitura dos 6 casos em que os dois rotuladores da âncora divergiram (`docs/projeto/ancora.md`): são as convenções acima, encarnadas em questões reais.
- Uma amostra mensal de 50 questões publicadas para auditoria. É isso que vai dizer se os 95% estão de pé, e é o que nenhum modelo pode fazer pelo senhor.
