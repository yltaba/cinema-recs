# Interface pelo Claude Code

Desde 07/10/2026 o Claude Code é a única interface conversacional do projeto; o Codex foi descontinuado.
O ranking, a configuração e os dados pessoais continuam no pipeline Python, e o contrato JSON da CLI
(`schema_version: 1`) não mudou de nome de campo. O registro da fase Codex está em [historico/](historico/).

## Arquivos

- [CLAUDE.md](../CLAUDE.md): regras permanentes, ambiente, testes e mapa. Carregado em toda sessão na pasta.
- [Skill filme](../.claude/skills/filme/SKILL.md): interpretação de pedidos, refinamentos, apresentação,
  salvos e feedback. Aparece como `/filme`, e o Claude também a usa sozinho em pedidos de filmes.
- [.claude/settings.json](../.claude/settings.json): permissões do projeto. Libera `uv run recs`/`pytest` e
  nega leitura do `.env`. Ajustes pessoais vão em `.claude/settings.local.json` (fora do Git).

## Equilíbrio de origem (07/10/2026)

Um pedido temático ("algo que me inspire para trabalhar amanhã") saiu quase todo japonês. Houve duas causas:
o agente acrescentou `--language ja` sem que o pedido justificasse, e a descoberta por perfil gastava dois dos
três slots com a mesma origem (país `JP` e idioma `ja`). As correções:

- Na seleção, sem país ou idioma pedidos, um país acima de `score.max_country_share` (0,4) faz a CLI acrescentar
  complementos de outras origens, até 2n, marcados `complemento_origem: true`. A seleção principal, os scores
  e a ordem não mudam. O diagnóstico ganha `availability.origem` (`cap`, `dominante`, `participacao`,
  `complementos`).
- Na descoberta por perfil, país e idioma correspondentes contam como uma origem só (`LANGUAGE_ORIGIN` em
  `candidates.py`).
- A skill proíbe filtros de origem e gênero não pedidos e manda conferir o equilíbrio da lista final.
- O eval ganhou `max_country_share20`. Comparativo em cópia isolada (5 seeds, holdout 15%):

  | variante | hit@20 | hit@50 | max_country_share20 |
  |---|---|---|---|
  | pesos atuais | 1,9% | 3,8% | 0,28 |
  | `language=0.5` | 2,9% | 3,8% | 0,30 |
  | `language=0` | 2,9% | 3,8% | 0,39 |
  | `language=0.5`, `country=0.5` | 2,9% | 3,8% | 0,39 |

  Reduzir os pesos de país e idioma aumenta a concentração no ranking geral, e a diferença de hit está no ruído
  (um filme). Por isso os pesos foram mantidos.
