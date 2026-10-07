# cinema-recs — instruções para Claude Code

Recomendador pessoal: export do Letterboxd → TMDB → perfil e ranking determinísticos → streaming no Brasil.
Responda em português. Execute comandos a partir da raiz do projeto.

## Uso conversacional

Para escolher filmes, refinar sugestões, consultar/salvar opções ou registrar feedback, use a skill `filme`
(`.claude/skills/filme/SKILL.md`) e siga o roteiro. Para manutenção de código, consulte `docs/ARQUITETURA.md`
e `docs/PLANO.md` conforme necessário.

## Regras permanentes

- A única entrada do Letterboxd é o export manual. Não acessar letterboxd.com, RSS ou fazer scraping.
- Use a CLI e seu ranking para recomendações pessoais; fundamente os dados apresentados na saída real.
- Não adicione filtros que o pedido não justifique: país, idioma e gênero só entram se o usuário pedir.
  Sem origem pedida, a lista apresentada deve ser equilibrada entre países (ver skill `filme`).
- Preserve restrições explícitas nos refinamentos. Não relaxe duração, serviços ou exclusões sem escolha do usuário.
- Streaming é metadado por padrão. "Hoje/agora" e estar em casal não implicam filtro de disponibilidade.
  Sem restrição explícita, catálogo e assinaturas não podem alterar universo, score pessoal ou ordem.
- `explore --json` é a entrada de descoberta ampla; Markdown é saída opcional. `now --json` usa o mesmo pipeline.
- Termine listas de filmes com: "Dados de filmes: TMDB. Dados de streaming: JustWatch."
- Credenciais são carregadas pelo programa de `TMDB_API_KEY`/`.env` (projeto ou ancestral). Nunca leia/imprima
  o conteúdo do `.env`, chaves, headers de autenticação ou URLs com credenciais. Prefira `.env` no projeto.
- Preserve banco, export, feedback e salvos. Testes usam dados sintéticos e bancos temporários, nunca o banco pessoal.
- Execute comandos que usam DuckDB sequencialmente; não abra dois escritores sobre o mesmo banco.
- Pesos e limites de ranking em `config.toml` só mudam após eval comparativo pertinente.
  O eval atual pode acessar a rede e modifica tabelas derivadas: use cópia isolada do projeto/dados para avaliação
  (ex.: `config.toml`, `overrides/` e `data/recs.duckdb` copiados para `data/evalcopy/`, rodando a CLI de lá;
  o `.env` do projeto é encontrado pelos diretórios ancestrais).
- Salvar e registrar feedback são ações locais: execute quando solicitadas explicitamente; um comentário
  sobre um filme permite oferecer o registro, não gravá-lo automaticamente. Não peça confirmação duplicada.

## Ambiente e verificação

Python 3.12+ e uv. Instalação: `uv sync --locked`. CLI: `uv run recs --help`.
Se o ambiente já estiver instalado e uv estiver indisponível, use `.\.venv\Scripts\recs.exe` no Windows.

Testes sem rede: `uv run pytest -p no:cacheprovider -q`.
Alternativa no ambiente existente: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q`.
Se o diretório temporário padrão do pytest der `PermissionError`, acrescente `--basetemp <pasta temporária>`.
Rode testes pertinentes ao código alterado. Não execute ingestão, eval ou gravações pessoais só para validar uma mudança.

## Mapa

- `src/recs/`: pipeline Python, um módulo por etapa; `cli.py` expõe Typer.
- `config.toml`: configuração, pesos e provedores assinados.
- `data/`: export e DuckDB, ignorados pelo Git.
- `overrides/`: matching, feedback e salvos persistentes.
- `reports/`: relatórios Markdown com data; disponibilidade histórica não é uma consulta atual.
- `.claude/skills/filme/`: roteiro conversacional; `.claude/settings.json`: permissões do projeto.
- `USO.md`: comandos e exemplos; `docs/CLAUDE-CODE.md`: interface pelo Claude Code e estado da migração.
