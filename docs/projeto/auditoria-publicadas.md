# Auditoria cega das publicadas

Checagem feita depois da execução, sem gabarito da Vício: dois juízes independentes classificaram às cegas as questões que o pipeline publicou, e a decisão do pipeline foi comparada com cada parecer pela régua do cliente (igual, pai ou filho conta como acerto). Foi feita para as duas execuções completas: a primeira (16/10, 117 publicadas) e a canônica (18/10, 124 publicadas). Dados em `data/auditoria_publicadas.jsonl` (canônica) e `data/auditoria_publicadas_rodada1.jsonl` (primeira).

## Protocolo

- Os juízes são dois modelos de fronteira, distintos dos dois que votam no pipeline e usados por assinatura, sem API: juiz 1, Claude Fable 5.1 (via Claude Code, como agente, esforço de raciocínio extra alto); juiz 2, Codex CLI com o modelo gpt-6-astra (esforço de raciocínio alto, por assinatura). Prompt em `docs/projeto/prompts/auditoria-publicadas.md`. Cada um recebeu a árvore inteira (`docs/projeto/arvore-temas.md`) e as questões, com as mesmas regras de rotulagem da âncora (`docs/projeto/ancora.md`): a questão como um todo, subtema quando domina, pai quando a questão se espalha, 0 só para outra disciplina.
- Nenhum dos dois viu a decisão do pipeline, os votos, os candidatos nem este repositório; o juiz 1 foi instruído a não abrir arquivo nenhum além do prompt, e o juiz 2 rodou em sandbox só de leitura com o prompt pela entrada padrão.
- Os pareceres são por questão, então valem para qualquer rodada: as 94 questões publicadas nas duas rodadas foram julgadas uma vez; as 30 que só a canônica publicou foram julgadas depois, pelo mesmo protocolo.

## Resultado na execução canônica (124 publicadas)

| Medida | Valor | Intervalo 95% |
|---|---|---|
| Precisão segundo o juiz 1 | 123 de 124 (99,2%) | 96,3% a 99,9% |
| Precisão segundo o juiz 2 | 119 de 124 (96,0%) | 91,3% a 98,4% |
| Certa para os dois juízes | 119 de 124 (96,0%) | |
| Certa para pelo menos um | 123 de 124 | |
| Juízes compatíveis entre si (régua) | 120 de 124 | |
| Precisão onde os juízes concordam | 119 de 120 (99,2%) | |

Por regra de decisão (certa para os dois): regra 2 (mesmo tema, confiança alta), 99 de 101; regra 3 (pai de dois subtemas), 20 de 23.

A previsão feita antes, só com o corpus, era 0,98 com intervalo 0,96 a 1,00. Os dois juízes caem dentro dela.

## Resultado na primeira execução (117 publicadas)

Juiz 1: 116 de 117 (99,1%, intervalo 96,0% a 99,9%). Juiz 2: 113 de 117 (96,6%, 92,0% a 98,8%). Certa para os dois: 113. A previsão daquela rodada era 0,97 com intervalo 0,94 a 1,00. As quatro contestadas são as mesmas quatro primeiras da tabela abaixo.

## As publicadas contestadas

| Questão | Pipeline | Juiz 1 | Juiz 2 | Leitura |
|---|---|---|---|---|
| Q0068 | Crimes Contra a Administração Pública (regra 3, pai) | Condescendência Criminosa (ok) | Crimes Contra a Fé Pública | Miscelânea de cinco crimes de títulos distintos; os dois juízes deram confiança 0,4. Questão mista, sem tema que a represente. |
| Q0119 | Lei Penal no Tempo e no Espaço | Lei penal no Tempo (ok) | Punibilidade > Abolitio Criminis | Abolitio criminis é lei penal no tempo e é causa de extinção da punibilidade; a árvore tem os dois nós em ramos diferentes. Convenção da equipe decide. |
| Q0167 | Procedimento do Tribunal do Júri | igual (ok) | Competência > Modificação de Competência | Desaforamento está no capítulo do júri no CPP, mas é modificação de competência. Mesmo caso de nó sobreposto. |
| Q0202 | Crimes Contra a Dignidade Sexual (regra 3, pai) | Erro de Tipo | Erro de Tipo | A única em que os dois juízes discordam do pipeline: caso do art. 218-B cujo núcleo é o desconhecimento da menoridade. O pipeline classificou pelo crime; os juízes, pelo instituto da parte geral. |
| Q0275 | Procedimento Sumaríssimo (regra 3, pai) | igual (ok) | Comunicação dos Atos Processuais | Citação e intimação no rito dos juizados; o juiz 2 preferiu o instituto, o pipeline o rito. Só na canônica. |

Quatro das cinco são nós sobrepostos ou questão mista, o mesmo padrão que apareceu na âncora e na checagem do corpus. A Q0202 é a mais instrutiva: quando uma questão narra um crime específico para cobrar um instituto da parte geral, a árvore oferece dois lugares legítimos, e a régua conta um deles como erro.

## Limitações

Juízes são modelos, não a equipe da Vício; podem compartilhar vieses com os modelos do pipeline, embora sejam de fornecedores e configurações diferentes e não tenham visto a lista de candidatos. O intervalo do juiz mais rigoroso vai até 91%, então 124 questões não bastam para garantir os 95% com 95% de confiança; o que a auditoria mostra é que a estimativa pontual fica acima da régua pelos dois juízes, nas duas rodadas, e que os erros contestados são de fronteira, não de leitura.
