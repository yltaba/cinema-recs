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
| 8. Interface Codex | `AGENTS.md`, `.agents/skills/filme/SKILL.md`, JSON da CLI | implementada; ver validação em `docs/MIGRACAO-CODEX.md` |

## Fase 7 — modo contexto

Pedidos em linguagem natural ("estou com minha namorada e queremos ver um filme engraçado") redirecionam
a busca sem abandonar o perfil. O Codex faz a interpretação; o `recs` continua determinístico.

- `recs now` com flags estruturadas: `--genre`, `--max-runtime`/`--min-runtime`, `--subscribed-only`,
  `--streaming-only`, `--language`, `--country`, `--years`, `--prefer`/`--avoid` (keywords), `--exclude`;
  saída em tabela e `--json`. `recs keywords <termo>` lista os nomes de keyword existentes.
- Pool ampliado pelo contexto e por features do perfil via `/discover/movie`; provedores somente
  com filtro explícito. Streaming não participa do score pessoal nem da ordem sem restrição.
- Score = afinidade com o perfil × encaixe no contexto (keywords de tom como ajuste leve, filtros rígidos).
- `AGENTS.md` e skill `$filme` orientam o Codex a traduzir pedidos em flags, preservar restrições nos
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

A adoção do Codex foi solicitada em 06/10/2026 após o cancelamento do Claude Code; não depende de um piloto
comparativo entre os dois agentes. O roteiro antigo foi substituído pelas instruções nativas do Codex.
Consulte `docs/MIGRACAO-CODEX.md` para entregas e verificações. A avaliação anterior fica como registro histórico
e backlog técnico; migração da interface não significa conclusão de todas as melhorias de algoritmo, ingestão e eval.
