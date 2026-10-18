# Prompt da auditoria cega das publicadas

Dado aos dois juízes com a árvore completa e as questões publicadas (117 da primeira rodada; depois as 30 que só a rodada canônica publicou), sem a decisão do pipeline. Juiz 1: Claude Fable 5.1, via Claude Code, agente com esforço de raciocínio extra alto, instruído a não abrir nenhum arquivo do repositório além do prompt. Juiz 2: Codex CLI com gpt-6-astra, esforço alto, sandbox só de leitura, prompt pela entrada padrão. Resultado em `data/auditoria_publicadas.jsonl` e `data/auditoria_publicadas_rodada1.jsonl`; leitura em `docs/projeto/auditoria-publicadas.md`.

```text
Você é um especialista em Direito Penal, Processo Penal, Legislação Penal Especial e Criminologia. Vou te dar a árvore de temas de uma plataforma de estudos e 117 questões reais de concurso. Para cada questão, escolha o tema da árvore em que ela deve ser classificada, pensando no aluno que estuda por tema.

Regras:
1. Escolha o tema mais específico que cobre o núcleo da questão (a questão como um todo, não só a alternativa correta).
2. Se a questão cobre vários subtemas do mesmo tema sem um dominante, escolha o tema pai (nível 1).
3. Se nenhum tema da árvore serve (questão de outra disciplina), use tema_id 0.
4. Temas introdutórios (conceito, fontes, princípios, sistemas) só quando a questão é sobre o conceito ou princípio em si.
5. Use só ids que existem na árvore abaixo. Nunca use a raiz de disciplina.

Responda SOMENTE com 117 linhas, uma por questão, na ordem dada, cada uma um JSON válido no formato:
{"id": "Q0001", "tema_id": 1234, "confianca": 0.8, "justificativa": "uma frase"}
Sem texto antes ou depois, sem cercas de código.
```

Regras adicionais dadas ao juiz 1 como agente: não abrir `publicacao.csv`, `data/intermediarios`, `data/cache`, `relatorio.md` nem `docs/`; ler as alternativas; gravar exatamente uma linha JSON por questão, na ordem do prompt; conferir ao final que todos os ids estão presentes uma vez e que cada `tema_id` existe na árvore.
