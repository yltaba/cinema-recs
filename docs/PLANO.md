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
| 4. Retrieval, elegibilidade, score, contexto, disponibilidade | `recs explore`, `recs now` | separada; relatório opcional |
| 5. Rerank com LLM | — | descartada |
| 6. Eval offline (holdout) e feedback | `recs eval`, `recs feedback` | feita |
| 7. Modo contexto | `recs now`, `recs keywords` + skill `filme` | feita; perfil de casal fora do escopo |
| 8. Interface conversacional | `CLAUDE.md`, `.claude/skills/filme/SKILL.md`, JSON da CLI | Claude Code desde 07/10/2026; ver `docs/CLAUDE-CODE.md` |
| 9. Equilíbrio de origem | `score.max_country_share`, `complemento_origem`, `max_country_share20` | feita; pesos mantidos após eval |

## Fase 7 — modo contexto

Pedidos em linguagem natural ("estou com minha namorada e queremos ver um filme engraçado") redirecionam
a busca sem abandonar o perfil. O agente faz a interpretação; o `recs` continua determinístico.

- `recs now` com flags estruturadas: `--genre`, `--max-runtime`/`--min-runtime`, `--subscribed-only`,
  `--streaming-only`, `--language`, `--country`, `--years`, `--prefer`/`--avoid` (keywords), `--exclude`;
  saída em tabela e `--json`. `recs keywords <termo>` lista os nomes de keyword existentes.
- Pool ampliado pelo contexto e por features do perfil via `/discover/movie`; provedores somente
  com filtro explícito. Streaming não participa do score pessoal nem da ordem sem restrição.
- Score = afinidade com o perfil × encaixe no contexto (keywords de tom como ajuste leve, filtros rígidos).
- `CLAUDE.md` e a skill `filme` orientam o agente a traduzir pedidos em flags, preservar restrições nos
  refinamentos e apresentar 3–5 opções com os motivos retornados, quando disponíveis.
- Perfil de casal só deve ser retomado com segundo histórico real e uso recorrente que o justifique.

## Reforma de outubro de 2026

Plano de commits, impacto, migrações e riscos: [REFORMA-ARQUITETURA.md](REFORMA-ARQUITETURA.md).
Implementados: invariantes de disponibilidade, seleção progressiva, diagnósticos, fontes de retrieval,
discover geral, explore com relatório opcional, interações locais, feedback canônico, perfil JSON e
NDCG/MRR/diversidade no eval. Pesos preservados; nenhuma avaliação real sobre o banco pessoal.

Limites deliberados: não há rerank suave por preferência de streaming, aprendizado das interações,
aprendizado negativo novo de `disliked`, perfil de casal ou medição de qualidade com histórico real nesta entrega.

## Migração e melhorias

O Codex foi adotado em 06/10/2026 e descontinuado em 07/10/2026; o projeto voltou a ser 100% Claude Code
(`CLAUDE.md`, `.claude/skills/filme/`). Estado atual em `docs/CLAUDE-CODE.md`; o registro da fase Codex e a
avaliação anterior ficam em `docs/historico/` como histórico e backlog técnico; migração da interface não significa conclusão de todas as melhorias de algoritmo, ingestão e eval.
