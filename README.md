# cinema-recs

Recomendador pessoal de filmes em linha de comando. Ele lê o export do Letterboxd, monta um perfil de gosto com
dados do TMDB e sugere filmes com a disponibilidade no streaming brasileiro.

```
export do Letterboxd ──► matching TMDB ──► enriquecimento (cache) ──► perfil de gosto
                                                                        │
             relatório / sugestões para o momento ◄── score ◄── candidatos (TMDB)
```

- **`recs explore --json`** faz descoberta ampla. Streaming é metadado e só restringe resultados quando
  solicitado. `--markdown caminho.md` gera um relatório opcional; `recommend` continua como atalho de relatório.
- **`recs now`** faz sugestões para o momento ("comédia policial nos meus serviços", "terror dos anos 70").
  O contexto define o recorte e o perfil define a ordem. No Claude Code, aberto nesta pasta, basta pedir em português
  (veja [USO.md](USO.md), [CLAUDE.md](CLAUDE.md) e a [skill filme](.claude/skills/filme/SKILL.md)).
- **`recs eval`** é uma avaliação por holdout. Ela esconde parte dos filmes que você avaliou bem e mede se o
  sistema os recuperaria. Toda mudança de peso passa por ela.

## Usar pelo Claude Code

Abra o Claude Code nesta pasta e peça, por exemplo:

> Quero uma comédia policial para hoje, até 110 minutos, nos meus streamings.

Depois refine: "até 90 minutos", "esse segundo já vimos", "salve o primeiro". O Claude Code opera a CLI local,
apresenta os dados retornados e mantém as restrições da conversa. Para chamar o roteiro explicitamente,
use `/filme` junto ao pedido. Sem país ou idioma pedidos, a lista é equilibrada entre origens.

A chave TMDB é a única credencial; nenhuma API de LLM é chamada pelo programa.
O ambiente Python e o histórico preparado abaixo continuam necessários. Não há perfil de casal implementado.
Interface e decisões recentes: [docs/CLAUDE-CODE.md](docs/CLAUDE-CODE.md).

## Regras do projeto

- **Sem acesso ao letterboxd.com.** Os termos de uso (seção 6.11) proíbem coleta automatizada. A única entrada
  é o ZIP exportado manualmente em *Settings → Import & Export*.
- Os dados de filmes vêm da API v3 do TMDB, e os dados de streaming são do JustWatch, servidos pelo TMDB. Todo
  relatório termina com a atribuição.
- Segredos ficam só no `.env`. O `.env` e a pasta `data/` estão no `.gitignore`.

## Instalação

Requisitos: Python 3.12 e [uv](https://docs.astral.sh/uv/).

```powershell
winget install astral-sh.uv          # se ainda não tiver o uv
cd cinema-recs
uv sync --locked
```

Crie um `.env` na pasta do projeto ou em qualquer pasta acima dela:

```
TMDB_API_KEY=sua_chave_v3
```

A chave é gratuita em <https://www.themoviedb.org/settings/api>.

## Primeiro uso

```powershell
uv run recs ingest ..\letterboxd-export.zip   # ZIP ou pasta descompactada
uv run recs match                               # Letterboxd → TMDB; revise overrides/unmatched.csv
uv run recs enrich                              # baixa metadados (só na primeira vez; depois vem do cache)
uv run recs profile                             # confere o perfil de gosto
uv run recs recommend                           # gera reports/AAAA-MM-DD.md
```

O dia a dia está em [USO.md](USO.md), e os detalhes de funcionamento em
[docs/ARQUITETURA.md](docs/ARQUITETURA.md). O status das fases está em [PLANO.md](docs/PLANO.md).

## Desenvolvimento

```powershell
uv run pytest -p no:cacheprovider
```

| pasta | conteúdo |
|---|---|
| `src/recs/` | código, um módulo por etapa |
| `CLAUDE.md` | regras permanentes do Claude Code |
| `.claude/skills/filme/` | roteiro conversacional de filmes |
| `.claude/settings.json` | permissões do projeto (nega leitura do `.env`) |
| `tests/` | testes (pytest, sem rede) |
| `config.toml` | pesos, limites e serviços assinados |
| `overrides/` | arquivos editáveis: correções de matching, feedback, salvos |
| `seeds/` | listas curadas opcionais (`*.csv` com `name,year`) |
| `reports/` | relatórios gerados |
| `data/` | export descompactado e banco DuckDB (fora do git) |

Dados de filmes: TMDB. Dados de streaming: JustWatch.
