# Classificação de tópicos: case Vício

Pipeline que classifica 359 questões de Penal, Processo Penal, Legislação Penal Especial e Criminologia nos temas da plataforma da Vício, decidindo entre `publicar`, `revisar` e `fora`. O enunciado original está em `docs/case/`.

## Como rodar

```bash
uv python install 3.12 && uv sync
cp .env.example .env            # chaves opcionais: o cache commitado reproduz tudo sem elas
docker compose up -d            # Weaviate; opcional, há substituto em memória
uv run classificar tudo
```

`uv run classificar tudo` gera `publicacao.csv` e `previsao.txt` na raiz. As etapas também rodam separadas: `candidatos`, `ancora`, `votos`, `vizinhanca`, `calibrar`, `decidir`, `publicar`. Testes: `uv run pytest`.

Os intermediários commitados em `data/intermediarios/` e o cache em `data/cache/` são o caminho de reprodução: `uv run classificar tudo` reaproveita candidatos e vizinhança prontos, lê votos e embeddings do cache e reproduz `publicacao.csv` sem chaves e sem Docker. `uv run classificar tudo --recalcular` recalcula todas as etapas (a planilha da âncora nunca é regravada), e o que não estiver no cache vai às APIs, então ele precisa das chaves no `.env`. A execução canônica usou o Weaviate via Docker (`docker compose up -d`) e os modelos de `.env.example`.

## O que gera cada arquivo

| Arquivo | Gerado por |
|---|---|
| `data/intermediarios/candidatos_*.jsonl` | `classificar candidatos` |
| `data/ancora_para_rotular.csv` | `classificar ancora` |
| `data/intermediarios/votos_llm_*.jsonl` | `classificar votos` |
| `data/intermediarios/vizinhanca_*.jsonl` | `classificar vizinhanca` |
| `data/intermediarios/limiares.json`, `calibracao_*.csv`, `calibracao_resumo.json` | `classificar calibrar` |
| `data/intermediarios/decisoes_questoes.jsonl` | `classificar decidir` |
| `publicacao.csv`, `previsao.txt` | `classificar publicar` |

## Documentos

- Spec de design: `docs/projeto/specs/2026-10-14-classificacao-topicos-design.md`
- Plano do pipeline: `docs/projeto/plans/2026-10-14-pipeline-central.md`

As seções de decisões manuais, modelos usados, custo e tempo entram ao final da execução.
