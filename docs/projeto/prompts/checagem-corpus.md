# Prompt da checagem independente do corpus

Dado ao Codex CLI (gpt-6-astra, esforço alto, sandbox só de leitura, prompt pela entrada padrão) com a árvore completa e 60 questões do corpus sorteadas com semente 42, sem o rótulo do agente de coleta. Resultado em `data/corpus_amostra_rotulador_independente.jsonl` e leitura em `docs/projeto/coleta-corpus.md`.

```text
Você é um especialista em Direito Penal, Processo Penal, Legislação Penal Especial e Criminologia. Vou te dar a árvore de temas de uma plataforma de estudos e 60 questões reais de concurso. Para cada questão, escolha o tema da árvore em que ela deve ser classificada, pensando no aluno que estuda por tema.

Regras:
1. Escolha o tema mais específico que cobre o núcleo da questão (a questão como um todo, não só a alternativa correta).
2. Se a questão cobre vários subtemas do mesmo tema sem um dominante, escolha o tema pai (nível 1).
3. Se nenhum tema da árvore serve (questão de outra disciplina), use tema_id 0.
4. Temas introdutórios (conceito, fontes, princípios, sistemas) só quando a questão é sobre o conceito ou princípio em si.
5. Use só ids que existem na árvore abaixo. Nunca use a raiz de disciplina.

Responda SOMENTE com 60 linhas, uma por questão, na ordem dada, cada uma um JSON válido no formato:
{"id": "C0001", "tema_id": 1234, "confianca": 0.8, "justificativa": "uma frase"}
Sem texto antes ou depois, sem cercas de código. Não leia nem altere arquivos.
```
