# Plano

Recomendador pessoal de filmes: export do Letterboxd → TMDB → sugestões com disponibilidade no Brasil.

Regras fixas:
- Sem scraping nem requisições ao letterboxd.com; a única entrada é o ZIP exportado manualmente.
- Dados de filmes vêm do TMDB (chave em `.env`). Todo relatório termina com
  "Dados de filmes: TMDB. Dados de streaming: JustWatch."
- Pesos só mudam acompanhados de um `recs eval` comparativo.

| fase | comando | status |
|---|---|---|
| 1. Ingestão e matching | `recs ingest`, `recs match` | feita |
| 2. Enriquecimento com cache | `recs enrich` | feita |
| 3. Perfil de gosto | `recs profile` | feita |
| 4. Candidatos, score, classes, relatório | `recs recommend` | feita |
| 5. Rerank com LLM | — | descartada |
| 6. Eval offline (holdout) e feedback | `recs eval`, `recs feedback` | feita |
| 7. Modo contexto | `recs now`, `recs keywords` + `CLAUDE.md` | feita (perfil de casal pendente) |

## Fase 7 — modo contexto

Pedidos em linguagem natural ("estou com minha namorada e queremos ver um filme engraçado") redirecionam
a busca sem abandonar o perfil. O Claude Code faz a interpretação; o `recs` continua determinístico.

- `recs now` com flags estruturadas: `--genre`, `--max-runtime`/`--min-runtime`, `--subscribed-only`,
  `--streaming-only`, `--language`, `--country`, `--years`, `--prefer`/`--avoid` (keywords), `--exclude`;
  saída em tabela e `--json`. `recs keywords <termo>` lista os nomes de keyword existentes.
- Pool ampliado pelo contexto via `/discover/movie` (gênero, `watch_region=BR`,
  `with_watch_providers` dos assinados, `vote_count` mínimo), além das fontes da Fase 4.
- Score = afinidade com o perfil × encaixe no contexto (keywords de tom como ajuste leve, filtros rígidos).
- `CLAUDE.md` (ou skill `/filme`) ensinando o Claude a traduzir pedidos em flags, refinar em mais uma
  rodada ("mais curto", "algo mais leve") e apresentar 3–5 opções com o motivo de cada uma.
- Depois: perfil de casal a partir de um segundo export (afinidade = mínimo dos dois; exclui o que
  qualquer um já viu).
