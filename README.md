# Case: classificação de tópicos

Processo seletivo da área de IA da **Vício (Método VDE)**.

## O problema

Na nossa plataforma, o aluno estuda por **tópico**: escolhe "Lei Maria da Penha" ou "Juiz das Garantias" e resolve as questões ligadas a ele. Se uma questão está no tópico errado, ele estuda a matéria errada.

Boa parte das questões foi classificada automaticamente, e isso criou tópicos genéricos que atraíram centenas de questões que não têm nada a ver com eles. Neste case você recebe **359 questões reais** de Penal, Processo Penal, Legislação Penal Especial e Criminologia, e a lista de temas em que elas podem ser classificadas.

Para cada questão, você decide:

| Decisão | Significado |
|---|---|
| **publicar** | Vai direto para o aluno, no tema que você escolheu |
| **revisar** | Vai para a fila de um especialista, com a sua sugestão |
| **fora** | Nenhum tema da lista serve |

**A régua:** das questões publicadas, pelo menos **95% precisam estar certas**. Dentro disso, quanto mais você publicar, melhor. Você também entrega uma previsão da sua própria precisão, um relatório e o código.

## Downloads

- 📄 **[Baixar o enunciado completo (PDF)](https://github.com/viciod/case-vicio-ia/raw/main/case-ia-classificacao-de-topicos.pdf)**: leia antes de começar. Tem a régua, o formato de entrega e os critérios de avaliação.
- 📦 **[Baixar os anexos (ZIP)](https://github.com/viciod/case-vicio-ia/raw/main/anexos-case-ia.zip)**: `questoes.jsonl`, `temas.csv`, `LEIA-ME.md` (formatos) e `entrega_modelo.csv`.

## Entrega

- **Prazo:** até domingo, 18/10.
- **Formato:** um **repositório público no GitHub** com `publicacao.csv`, `previsao.txt`, o relatório (PDF ou Markdown) e o código. Envie o link para **carla@viciodeumaestudante.com.br**.
- **Código:** queremos ver **como a classificação foi feita**, do começo ao fim: pipeline, prompts, chamadas a modelos, as regras que decidem entre publicar, revisar e fora, e como você estimou a sua precisão. Mesmo que esteja bagunçado. Inclua um README dizendo como rodar e o que gera o `publicacao.csv`, e registre qualquer decisão tomada à mão.

Dúvidas: **carla@viciodeumaestudante.com.br**.
