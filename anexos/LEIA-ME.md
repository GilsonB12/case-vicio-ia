# Anexos — Case "Classificação de tópicos"

Todos os arquivos estão em UTF-8. CSVs separados por vírgula, com aspas quando necessário.

| Arquivo | Linhas | O que é |
|---|---|---|
| `questoes.jsonl` | 359 | Uma questão por linha: `id`, `enunciado_html` (HTML cru, como está no banco), `comando`, `alternativas`, `disciplina_origem` e `assunto_origem` (como vieram do site de origem; podem estar errados) |
| `temas.csv` | 377 | Os temas em que as questões podem ser classificadas, em árvore: Penal, Processo Penal, Direito Penal - Legislação Especial e Criminologia. `nivel` 0 = disciplina, 1 = tema, 2 = subtema. Inclui `descricao` e `status` (não use temas inativos) |
| `entrega_modelo.csv` | 2 | Exemplo do formato de `publicacao.csv` |

Nenhuma questão vem classificada. Todas as 359 precisam de uma decisão.

## Formatos de entrega

### `publicacao.csv`: uma linha para **cada uma das 359 questões**

| Coluna | Valor |
|---|---|
| `id` | Q0001… |
| `decisao` | `publicar`, `revisar` ou `fora` |
| `tema_central_id` | `tema_id` de `temas.csv`. Obrigatório em `publicar` e em `revisar` (a sua sugestão). Vazio em `fora` |
| `extras_ids` | Outros `tema_id` que a questão também cobre, separados por `;`. Pode ficar vazio |
| `confianca` | De 0 a 1: a chance de o tema central estar certo |
| `motivo` | Curto. Obrigatório em `revisar` e em `fora` |

### `previsao.txt`

```
precisao_prevista: 0.00   # fração das publicadas que estará certa
precisao_intervalo: 0.00-0.00
cobertura_prevista: 0.00  # fração das questões que você publicou
cobertura_intervalo: 0.00-0.00
```
Depois dessas linhas, explique em texto livre como chegou nos números.
