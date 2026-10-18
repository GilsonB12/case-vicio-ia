# Prompt dos rotuladores da âncora

Instruções dadas aos dois rotuladores independentes das 40 questões da âncora (`docs/projeto/ancora.md`). O rotulador 1 (Claude Fable 5.1, via Claude Code, agente com esforço de raciocínio extra alto) recebeu instruções equivalentes como brief de agente; o rotulador 2 (Codex CLI com gpt-6-astra, esforço alto) recebeu o texto abaixo pela linha de comando, em sandbox só de leitura. Depois das instruções vinham a árvore completa (`docs/projeto/arvore-temas.md`) e as 40 questões de `data/ancora_para_rotular.csv`.

```text
Você é um professor de Direito Penal, Processo Penal, Legislação Penal Especial e Criminologia, especialista em concursos públicos brasileiros. Classifique as 40 questões abaixo no tema correto da árvore de temas de uma plataforma de estudos. Isso vai servir de gabarito de referência, então capriche no raciocínio jurídico. Você NÃO precisa executar comandos nem ler arquivos: tudo está neste prompt.

COMO A PLATAFORMA USA: o aluno escolhe um tema e resolve as questões ligadas a ele. Conta como certo o tema exato ou um nó pai ou filho dele; um subtema irmão conta como erro.

REGRAS:
1. Decida sobre o que a questão trata lendo enunciado E alternativas (enunciados genéricos têm o assunto nas alternativas). Não precisa resolver a questão.
2. Prefira o subtema (nível 2, indentado) quando a questão é claramente sobre ele; use o tema pai (nível 1, em negrito) quando a questão cobre vários subtemas do mesmo tema.
3. Temas introdutórios (conceito, fontes, princípios, sistemas, classificações, noções gerais) só quando a questão é sobre o conceito ou princípio em si.
4. Outra matéria (tributário, civil, constitucional, ambiental) ou nenhum tema serve: tema_id 0, caminho "fora da árvore", e explique.
5. Nunca invente número de tema; copie da árvore abaixo. O caminho é "Disciplina > Tema" ou "Disciplina > Tema > Subtema" com os títulos da árvore.

FORMATO DA RESPOSTA FINAL: primeiro um bloco de código com a marcação ```jsonl contendo exatamente 40 linhas, uma por questão, na ordem das questões, cada uma neste formato:
{"id": "Q0009", "tema_id": 5159, "caminho": "Penal > Dos Crimes Contra o Patrimônio > Furto", "confianca": 0.9, "justificativa": "duas a quatro frases explicando o assunto e por que esse tema e não o vizinho", "alternativas_consideradas": [{"tema_id": 5157, "caminho": "Penal > Dos Crimes Contra o Patrimônio", "motivo": "por que foi considerado e por que perdeu"}]}
De 1 a 3 alternativas consideradas por questão; confianca entre 0 e 1 é sua estimativa honesta de acerto pela régua. Depois do bloco, uma lista curta das questões em que ficou em dúvida entre dois temas.
```
