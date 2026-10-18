# Âncora manual: protocolo e decisões

A âncora são 40 das 359 questões do case com um tema de referência fechado à mão, sem ver a saída do pipeline. Ela existe para uma coisa: checar se a precisão prevista pela calibração no corpus (seção 10 da spec) se sustenta nas questões reais. Nas questões da âncora que o pipeline publicar, compara-se a precisão observada com a prevista; se a diferença não cabe no intervalo, o intervalo é alargado e o `previsao.txt` explica.

## Amostra

`classificar ancora` sorteia as 40 com semente fixa, estratificadas por `disciplina_origem`, antes de qualquer chamada a modelo, e grava `data/ancora_para_rotular.csv` com o texto de cada questão. A planilha nunca é regravada depois de rotulada.

## Quem rotulou e como

O autor do projeto não tem formação jurídica, e o case não fornece nenhuma questão rotulada. Em vez de um rótulo solitário de quem não domina o assunto, a âncora foi fechada em duas etapas:

1. **Dois rotuladores independentes.** Dois modelos de fronteira, distintos dos dois usados no pipeline, Claude Fable 5.1 (via Claude Code, como agente, esforço de raciocínio extra alto) como rotulador 1 e Codex CLI com o modelo gpt-6-astra (esforço de raciocínio alto, por assinatura) como rotulador 2 (prompt em `docs/projeto/prompts/rotuladores-ancora.md`), receberam a árvore completa (`docs/projeto/arvore-temas.md`) e as 40 questões, em sessões separadas, sem acesso a candidatos, votos ou decisões do pipeline e sem ver um ao outro. Cada um devolveu, por questão, tema, confiança, justificativa e as alternativas que considerou e descartou. As propostas estão em `data/ancora_rotulos_modelo_1.jsonl` e `data/ancora_rotulos_modelo_2.jsonl`.
2. **Arbitragem.** O autor revisou as 40 num modo da tela de revisão feito para isso (o modo Âncora, que existiu durante o projeto e foi removido da interface final; o código está no histórico do git), lendo a questão e as duas justificativas, e procurou na internet as questões em dúvida, em sites de questões comentadas. O resultado é `data/ancora_manual.csv`, com `id`, `tema_id` e `observacao`. Em `tema_id`, 0 quer dizer fora da árvore, e a raiz de uma disciplina quer dizer que qualquer tema de nível 1 dela serve.

Concordância entre os rotuladores: 34 das 40 idênticas; 2 diferem só de nível (pai e filho da mesma linha, que a régua do cliente conta como acerto); 4 divergem de verdade. Nas 34 idênticas, a arbitragem confirmou o consenso. As 6 restantes estão na tabela abaixo.

## Regras de arbitragem

1. **A questão como um todo decide, não a alternativa correta.** O tema é o que o aluno precisa saber para resolver a questão, porque é por tema que ele vai estudar. O pipeline não recebe gabarito, então um critério baseado na alternativa correta mediria o sistema contra algo que ele não tem como seguir. A alternativa correta só desempata quando a questão está dividida.
2. **Filho quando ele existe e cobre o núcleo da questão; pai quando o núcleo não tem nó próprio ou está espalhado por vários filhos sem um dominante.** A régua aceita os dois, mas o rótulo deve ser o mais fiel, não o mais conveniente.
3. **Questão que mistura vários temas de nível 1 da mesma disciplina, sem um dominante, fica no pai comum, a raiz da disciplina.** A raiz nunca é publicada pelo pipeline, mas como âncora ela diz: qualquer um dos temas misturados conta como acerto, e nada mais. Aplicado uma vez (Q0282). **Fora (0)** fica reservado para questão que nenhum tema da lista serve; não aconteceu nas 40.
4. **Classificação de sites externos é evidência auxiliar, não gabarito.** Esses sites têm taxonomias próprias, às vezes mais finas que a árvore do cliente.
5. Divergência relevante fica anotada na coluna `observacao`.

## Casos em que os rotuladores não coincidiram

| Questão | Rotulador 1 | Rotulador 2 | Decisão | Motivo |
|---|---|---|---|---|
| Q0106 (pendura) | 5166 Estelionato | 5157 Dos Crimes Contra o Patrimônio | **5157** | A pendura é o art. 176 do CP ("outras fraudes"), que não tem nó na árvore. A árvore dá nós próprios a outros crimes do mesmo capítulo (Abuso de Incapazes, Fraude à Execução), então "Estelionato" aqui é o art. 171. Um site de questões classifica a questão como "Outras fraudes", nó que a árvore não tem. Regra 2: sem filho, o pai. |
| Q0163 (diretor abre carta de preso) | 5133 Inviolabilidade de domicílio, correspondência e segredos | 4684 Abuso de Autoridade | **4684** | Três das alternativas invocam a Lei de Abuso de Autoridade e o comando pergunta pela responsabilidade penal do diretor como autoridade; a violação de correspondência do CP é o contraponto. O rotulador 1 preferiu o CP porque a lei citada foi revogada; a arbitragem seguiu o que a questão cobra, não o que sobreviveu. |
| Q0180 (busca domiciliar noturna sem mandado) | 5554 Busca e Apreensão | 5594 Prova Ilegal e Prova Ilícita | **5554** | O conhecimento decisivo são os requisitos da busca domiciliar (ordem judicial, horário, flagrante). A ilicitude da prova é a consequência, não o que se testa. |
| Q0187 (Dionísio, corrupção) | 5209 Efeitos da Condenação Penais e Extrapenais | 5199 Teoria da Pena (pai) | **5209** | Quatro das cinco alternativas tratam de efeitos da condenação; a progressão de regime (alternativa correta) é um extra. O título dado à questão por um site de questões comentadas confirma os dois assuntos, nessa ordem de peso. Regra 2: há filho dominante. |
| Q0282 (cinco leis especiais) | 4704 Lei Maria da Penha | fora | **4683 Direito Penal - Legislação Especial (raiz)** | Questão mista: duas alternativas de Lei Maria da Penha, duas do Estatuto do Desarmamento, uma de Crimes de Racismo. Nenhum tema sozinho representa o conjunto, mas a questão está inteira dentro da legislação especial, então não é fora. A âncora fica no pai comum das três leis: publicar qualquer uma delas conta como acerto. Editada direto no CSV, porque a tela só oferece temas publicáveis. O rótulo alternativo seria 4704 como tema central, com as outras duas leis como extras. |
| Q0299 (escolas e teorias criminológicas) | 4387 Teorias de Nível Sociológico | 4373 Escolas Criminológicas | **4387** | A alternativa correta e o eixo da questão são as teorias da reação social (labelling approach, criminologia crítica). Escola positivista e teoria da pena aparecem como distratores. |

## Efeito sobre a checagem

A régua conta pai e filho como acerto. Âncora no pai (Q0106) aceita previsão em qualquer filho daquele pai; âncora na raiz da disciplina (Q0282) aceita qualquer tema de nível 1 daquela disciplina e rejeita o resto; âncora em fora (0), se houvesse, faria qualquer publicação daquela questão contar como erro. Com poucas dezenas de questões publicadas dentro da âncora, cada rótulo move a precisão observada em vários pontos percentuais, então a checagem só detecta diferenças grandes entre previsto e observado, como a spec já diz.

## Limitações

A âncora não é um gabarito de especialista. É o consenso de dois rotuladores fortes e independentes, arbitrado por quem não é jurista, com apoio de sites de questões. A concordância alta nas 34 sugere que a maioria é confiável; o risco está concentrado nas 6 difíceis, que são exatamente as questões que o pipeline também tende a mandar para revisão. O relatório declara isso, e a produção resolve o problema de origem: cada decisão do professor na fila de revisão vira rótulo, e em poucas semanas existe a base dourada que o case, de propósito, não forneceu.
