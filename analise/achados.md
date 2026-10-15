# Achados da análise exploratória

O que o notebook `analise/analise_exploratoria.ipynb` encontrou nas 359 questões e nos 377 temas, antes de qualquer classificação. Todo número e todo id daqui pode ser conferido no notebook, que usa só os arquivos de `anexos/` e não chama modelo de IA. Questões aparecem pelo id (Q0078); temas, pelo número do tema (tema 4696), que nas tabelas fica na coluna `tema_id`.

Para situar: em cada questão, o pipeline separa primeiro os temas candidatos, os poucos temas da árvore cujo texto mais se parece com o da questão, e dois modelos de linguagem escolhem cada um o seu tema entre eles (são os votos dos modelos; questões de referência parecidas, com tema conhecido, dão um terceiro voto). Regras simples transformam os votos em `publicar`, `revisar` (uma pessoa confere) ou `fora` (a questão não cabe em nenhum tema da árvore, por exemplo por ser de outra disciplina), e o resultado vai para o arquivo `publicacao.csv`.

## 1. Resumo

- **Às vezes o assunto está só nas alternativas.** 20 questões têm enunciado genérico, como "Assinale a alternativa correta."; a Q0090 e a Q0205 têm o mesmo enunciado (só mudam as maiúsculas) e nada mais em comum.
- **Os rótulos da fonte não servem para decidir.** Das 8 questões com disciplina de origem fora do escopo, só a Q0142 (imposto ITCD) é de outra matéria. Nas amostras dos 6 assuntos de origem mais frequentes, só um descreve bem as questões.
- **A árvore de temas tem defeitos:** 20 duplicados sem descrição, 7 títulos com erro, 2 inativos, 7 sem questões na fonte e 1 descrição com uma palavra em árabe. O pipeline trata ou registra cada um.
- **Texto mal digitalizado não se separa pela medida que usamos**, a proporção de palavras desconhecidas. A Q0078, com corrupção de OCR, fica em 12º lugar entre 359, atrás de 11 questões limpas: a medida serve de triagem para leitura humana, não de detector.
- **A limpeza do texto não perde conteúdo:** nenhuma questão tem imagem.

## 2. Os dados

| Item | Resultado |
|---|---|
| Questões | 359 |
| Disciplina de origem | 12 rótulos, contando o vazio, com a mesma matéria escrita de mais de um jeito ("Penal" e "Direito Penal"). 351 questões no escopo e 8 fora (Constitucional, Civil, Tributário, Ambiental, "Disciplina Unificada" e vazio) |
| Assunto de origem | 94 distintos; 18 questões sem assunto; o maior, "Concurso de Crimes", tem 43 |
| Formato | 255 com 5 alternativas, 46 com 4, 58 de Certo ou Errado |
| Sem comando | 94 questões (26%) |
| Enunciado, sem comando e alternativas | Mediana de 201 caracteres; metade entre 89 e 516; de 9 a 2.452; 51 com até 60 |
| HTML | Só formatação simples. A exceção é uma alternativa da Q0099 com 35.771 caracteres de HTML do Word, 166 depois de limpa. Nenhuma imagem |
| Temas | 377: 4 disciplinas na raiz, 111 temas e 262 subtemas. Penal 186, Processo Penal 138, Direito Penal - Legislação Especial 27, Criminologia 26. 375 ativos, 2 inativos |

## 3. A árvore de temas

| Defeito | tema_id | Para o aluno | Para a classificação |
|---|---|---|---|
| Duplicado sem descrição (20) | 6716 a 6738 (pula do 6728 para o 6732) | A mesma matéria em dois lugares, como "Lei Maria da Penha" em Penal (tema 6724) e em Legislação Especial (tema 4704); as questões dela podem ficar divididas. | Cada duplicado vira o tema original: 17 pelo título (sem o "(Parte N)" e sem diferença de maiúsculas), 3 por uma tabela de exceções feita à mão. Nenhum aparece em `publicacao.csv`. |
| Título com erro (7) | 4373, 4696, 5081, 5136, 5483, 5499, 5567 | Se a lista de temas mostra esses títulos, o aluno vê "Crimonológicas", "Estaturo", "Comeptência" e "Testemunhavel", e uma busca por "Estatuto" pode não achar o tema 4696. | Vale o id, então nada muda. O caso delicado é o tema 4696: o título errado é o do id que fica, e o duplicado tema 6722 tem o certo ("Estatuto do Idoso - Crimes"). Os títulos vão para o relatório. |
| Inativo (2) | 5078, 5234 | "Direito penal econômico" e "Tratados e convenções em matéria criminal" estão desativados: uma questão dessas matérias vai para outro tema ou para revisão, nunca para eles. | Ficam fora dos candidatos. |
| Zero questões na fonte (7) | 5090, 5139, 5163, 5190, 5522, 5549, 5558 | Temas como "Usurpação" e "Ação Controlada" existem, mas o aluno não tem o que praticar neles até a classificação trazer questões. | Continuam candidatos: o tema existe, só não tinha questões. |
| Caracteres estranhos (1) | 5530 | Se a descrição de "Procedimento Ordinário" aparece para o aluno, ele lê "o interrogatório como meio de الدفاع", com a palavra árabe para "a defesa". | A descrição entra no texto do tema comparado com as questões; efeito esperado pequeno, porque o resto é longo e correto. |

**O que corrigir na fonte.** Recomendamos:
- corrigir os 7 títulos, a começar pelo tema 4696, porque o id que fica é o que tem o erro;
- fundir ou aposentar os 20 duplicados;
- limpar a descrição do tema 5530;
- decidir o que fazer com os temas 5078 e 5234, que estão inativos;
- deixar de usar o assunto de origem para organizar ou navegar as questões (seção 4).

## 4. As lixeiras

O enunciado do case avisa que alguns assuntos de origem são lixeiras, rótulos largos onde caiu de tudo. Para os 6 assuntos mais frequentes, o notebook sorteou 8 questões de cada um e mostra o começo delas; a leitura vale para as amostras, não para o assunto inteiro. Três exemplos por assunto, com o começo do enunciado:

**Concurso de Crimes** (43 questões): lixeira. Nenhuma das 8 trata de concurso material, formal ou crime continuado.
- Q0039: "Suponha que todos os revendedores de gás liquefeito de petróleo (GLP) ajustem artificialmente preço…" (ordem econômica)
- Q0307: "Determinado policial militar efetuou a prisão em flagrante de Luciano…" (tortura por policial)
- Q0337: "A Lei nº 13.869/2019 dispõe sobre os crimes de abuso de autoridade…" (abuso de autoridade)

**Ação Penal (Parte 02)** (17): lixeira, com recurso, prisão, organizações criminosas, livramento condicional e prescrição.
- Q0151: "No que diz respeito às prisões e medidas cautelares no processo penal…"
- Q0200: "No que diz respeito às organizações criminosas…"
- Q0228: "Se o defensor de um condenado preso entender que ele faz jus ao livramento condicional…"

**Ação Penal (Parte 01)** (19): acerta parte. Metade da amostra trata de provas ou recursos; duas cabem no rótulo.
- Q0098: "A doutrina denomina “confissão qualificada” aquela em que o acusado…" (prova)
- Q0012: "Da decisão que rejeitar a denúncia oferecida nos termos do artigo 77 da Lei 9.099/1995…" (recurso)
- Q0240: "Pedro, que estava indiciado por crime de roubo, teve sua prisão decretada…" (prazo da denúncia: cabe)

**Ação Penal** (20): acerta parte.
- Q0152: "Nos crimes de ação privada, se comparecer mais de uma pessoa com direito de queixa…" (cabe)
- Q0305: "A ação penal pública é de iniciativa exclusiva do Ministério Público…" (cabe)
- Q0025: "A conduta do particular de solicitar vantagem de contribuinte autuado pela fiscalização…" (não cabe)

**Inquérito Policial** (19): acerta parte.
- Q0015: "Com relação ao inquérito policial, segundo o Código de Processo Penal." (cabe)
- Q0193: "Sobre o tema da colaboração premiada…" (não cabe)
- Q0320: "O Direito Processual Penal, doutrinariamente, elenca as espécies de testemunhas…" (não cabe)

**Teoria da Pena (Parte 02)** (18): coerente, com aplicação da pena e execução penal.
- Q0043: "Sobre a fixação da pena, tem-se o seguinte:"
- Q0052: "Uma pessoa presa em regime fechado, definitivamente condenada, prestou 300 dias de trabalho…"
- Q0250: "Sobre a determinação do regime inicial de cumprimento de pena…"

Nas amostras, só um dos 6 assuntos descreve bem o conteúdo; nos outros cinco, o rótulo acerta no máximo parte das questões.

## 5. Casos destacados

| id | O que tem de especial | O que o pipeline faz com ele |
|---|---|---|
| Q0142 | A única de fato fora das quatro disciplinas: isenção do imposto ITCD, direito tributário. | Nada próprio: `fora` sai dos votos dos modelos sobre o texto. |
| Q0014, Q0016, Q0036, Q0137, Q0218, Q0277, Q0309 | Disciplina de origem fora do escopo ou vazia, mas conteúdo penal: habeas corpus, prisão preventiva, violência doméstica, indiciamento, documento falso, crimes contra idoso, crime ambiental. | Classifica como as outras; o prompt (o texto enviado aos modelos) não mostra a disciplina de origem. |
| Q0090 e Q0205 | Mesmo enunciado, "Assinale a alternativa correta.", que 6 questões repetem; as duas só diferem nas maiúsculas e não têm mais nada em comum. | Classifica enunciado, comando e alternativas juntos; nada é descartado por repetir enunciado. |
| Q0078 | Corrupção de OCR ("oossstomnioconcunsos", "itercepiado", "dagrante"), mas legível: posse, porte e venda de arma. | Não corrige o texto; a marca de suspeita vai para o relatório e não muda a decisão. |
| Q0099 | Alternativa com 35.771 caracteres de HTML do Word. | A limpeza deixa 166 caracteres. |
| Q0240 | `\t` escrito como texto nas alternativas ("15\tdias"). | A limpeza troca por espaço. |
| Q0007 | Personagem chamado Gilson, o nome do autor deste trabalho: coincidência da fonte. | Trata como qualquer outra. |

## 6. Corrupção de OCR

OCR é a leitura automática de texto digitalizado; quando falha, deforma palavras, como na Q0078.

**Como foi medido.** Uma palavra conta como conhecida se aparece em pelo menos 2 textos do conjunto: as outras 358 questões e os caminhos e descrições dos temas. A medida de cada questão é a fração das suas palavras que não são conhecidas. Texto deformado sobe a medida, mas vocabulário raro e legítimo também.

**Resultado.** Mediana 0,141; percentil 90 (o valor abaixo do qual ficam 90% das questões) 0,266; máximo 0,456. A Q0078 tem 0,341 e fica em 12º entre 359; a Q0001, a primeira do arquivo, usada como exemplo limpo, tem 0,083. Das 64 palavras desconhecidas da Q0078, só 11 são lixo de OCR; as outras 53 são palavras comuns e nomes próprios que um conjunto pequeno não repete ("pistola", "raspada", "embaixo").

**Limiar e quem foi marcado.** O limiar 0,25 marca 48 questões (13%): pega a Q0078, deixa a Q0001 de fora e fica um pouco abaixo do percentil 90. As 11 acima da Q0078 são limpas, com vocabulário raro: autores da criminologia (Q0076, Q0002, Q0253), termos técnicos criminológicos (Q0066), narrativas cheias de nomes e palavras do dia a dia (Q0115, Q0302, Q0083, Q0329), legislação penal especial com vocabulário trabalhista e ambiental (Q0154, Q0344) e a Q0142, sobre ITCD. Mudar o limiar não resolve: acima de 0,30 ficam 20 questões, acima de 0,34 ficam 12, e nenhum limiar marca a Q0078 sem marcar junto pelo menos 11 limpas.

Por isso o resultado é uma **lista de triagem ordenada para leitura humana, não um detector**. Uma melhoria barata, fora do escopo, seria olhar só as palavras desconhecidas longas ou com sequências improváveis de letras, como "oossstomnioconcunsos".

## 7. O que isso muda no pipeline

- **Texto completo.** Enunciado, comando e alternativas entram juntos, e nenhuma questão é descartada por repetir enunciado.
- **Duplicados viram o original.** Os temas 6716 a 6738 (20 ids, porque a numeração pula do tema 6728 para o tema 6732) viram o tema original e nunca aparecem em `publicacao.csv`.
- **Rótulos da fonte não decidem.** Decidir `fora` pela disciplina de origem erraria 7 das 8 questões rotuladas fora do escopo. A decisão sai dos votos dos modelos, o prompt não mostra disciplina nem assunto de origem, e o assunto também fica fora da busca de candidatos.
- **Temas introdutórios com cautela.** Temas largos como "Conceito e Fontes do Direito Penal" (tema 5171), "Princípios do Direito Penal" (tema 5172) e "Princípios do Processo Penal" (tema 5582) atraem questões genéricas como as lixeiras; o prompt só os aceita quando a questão é sobre o conceito ou o princípio em si.
- **Inativos fora, temas sem questões dentro.** Os temas 5078 e 5234 não são candidatos; os 7 sem questões continuam. O texto de cada tema usado na comparação é o caminho na árvore mais a descrição, sem a frase da fonte com a contagem de questões.

## 8. O que fica para depois da execução

- Cruzar cada assunto de origem com o tema decidido, para medir quanto de cada lixeira foi para outros ramos da árvore.
- Ver a decisão dos casos destacados: se a Q0142 saiu como `fora`, como ficaram as 7 penais com rótulo errado, a Q0078 e as 48 marcadas pela triagem de OCR.
- O resto da seção 12 da spec (`docs/projeto/specs/2026-10-14-classificacao-topicos-design.md`): questões que cobrem vários temas, questões em que os modelos discordaram e por quê, e os gráficos de distribuição das decisões, confiança por regra e precisão por faixa no corpus de referência.
