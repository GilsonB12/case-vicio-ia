# Protocolo de coleta do corpus de referência

O corpus de referência é um conjunto de questões reais de concurso, com tema conhecido, usado em duas coisas: o voto por vizinhança do pipeline e a estimativa de precisão (seção 10 da spec). Ele não é coletado por código do repositório: agentes de pesquisa baseados em LLM, com acesso a busca e leitura de páginas, recebem lotes de temas e devolvem questões em JSONL. Este documento registra o protocolo, o prompt e os critérios, porque a coleta é uma decisão manual do projeto.

## Temas alvo e meta por tema

Os temas alvo são a união dos candidatos da primeira passada nas 359 questões mais os pais de nível 1 (`data/intermediarios/temas_alvo_corpus.json`): 341 temas. A meta de questões por tema segue o peso do tema, isto é, em quantas das 359 questões ele aparece entre os candidatos:

| Peso (questões em que é candidato) | Meta de questões no corpus |
|---|---|
| 10 ou mais | 6 |
| 4 a 9 | 4 |
| 1 a 3 | 2 |

Os lotes estão em `data/coleta/lotes.json`, balanceados pela meta total.

## Níveis de confiança da fonte

| Nível | Fontes | Exemplos |
|---|---|---|
| alta | Provas oficiais publicadas pelas bancas, ou sites de questões estabelecidos que classificam por assunto | PDFs de provas da Cebraspe, FGV, FCC, Vunesp, Cesgranrio; páginas públicas de questões do QConcursos, TecConcursos, Questões de Concursos |
| media | Cursos preparatórios com questões comentadas em páginas públicas | Estratégia Concursos, Gran Cursos, Direção Concursos, CERS |
| baixa | Blogs, fóruns e agregadores sem banca identificada | Qualquer outra página |

Questões sem banca ou ano identificável recebem no máximo `media`.

## Formato de saída

Um objeto JSON por linha, em `data/coleta/lote-NN.jsonl`:

```json
{"tema_id": 5159, "enunciado": "...", "comando": "...", "alternativas": {"A": "...", "B": "..."}, "url": "https://...", "site": "dominio.com.br", "banca_ano": "FGV 2023", "confianca_fonte": "alta"}
```

Regras: `enunciado` e `alternativas` copiados da página, sem comentários nem gabarito comentado; questões Certo/Errado usam `{"C": "Certo", "E": "Errado"}`; `comando` pode ficar vazio; `tema_id` é um dos temas do lote; uma questão não pode aparecer em dois temas.

## Prompt dos agentes

> Você é um pesquisador que monta um corpus de questões reais de concurso público brasileiro para calibrar um classificador de temas de Direito Penal, Processo Penal, Legislação Penal Especial e Criminologia. Para cada tema da sua lista, encontre em páginas públicas da internet questões reais de concurso que sejam claramente sobre aquele tema, na quantidade pedida. Use a busca na web com o título do tema e termos como "questão", "concurso", "prova", e leia a página antes de copiar. Copie o enunciado e as alternativas exatamente como estão; não copie comentários, gabarito comentado nem explicações. Registre a URL da página, o domínio, a banca e o ano quando aparecerem, e o nível de confiança da fonte pelos critérios dados. Não invente questões, não parafraseie, não use questões de sites que exigem login para mostrar o texto. Se uma questão serve para mais de um tema da lista, escolha o tema mais específico e use a questão uma vez só. Prefira questões recentes e de bancas conhecidas. Se não achar a quantidade pedida para um tema, entregue o que achou e diga quantas faltaram. Grave o resultado em JSONL no caminho indicado e devolva um resumo por tema: quantas encontrou, quantas faltaram e as consultas que funcionaram.

## Pós-processamento

1. Validação de formato e de `tema_id` (publicável e do lote).
2. Deduplicação interna por texto normalizado e por similaridade de embedding acima de 0,95.
3. Deduplicação contra as 359 por similaridade de embedding acima de 0,95, para nenhuma questão do case vazar para o corpus.
4. Remoção de questões sem alternativas ou com enunciado menor que 40 caracteres.
5. Gravação em `data/corpus_referencia.jsonl` com `id` sequencial `C0001...`, mantendo `url`, `site`, `banca_ano` e `confianca_fonte` como proveniência.

## Limitações conhecidas

Os rótulos do corpus vêm da classificação do site de origem ou da leitura do agente, não da equipe da Vício. Questões achadas por busca pelo nome do tema tendem a ser as mais fáceis daquele tema. As duas coisas puxam a precisão medida no corpus para cima; a reponderação por célula e a âncora manual mitigam, e o relatório declara.
