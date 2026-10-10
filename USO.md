# Como usar

Todos os comandos rodam de dentro da pasta `cinema-recs` com `uv run recs <comando>`. `--help` mostra as opções
de cada um.

## 1. Pedir um filme para agora

### Pelo Claude Code (recomendado)

Abra o Claude Code na pasta `cinema-recs` e peça em linguagem natural (ou invoque `/filme`):

> estou com minha namorada e queremos ver algo engraçado, nada pesado, até umas 2h
>
> quero ver uma comédia policial
>
> algum terror dos anos 70, qualquer streaming serve

O Claude Code transforma o pedido num `recs now --json` (ou `explore --json`), roda o comando e apresenta de 3 a 5 opções, se disponíveis, com o motivo de cada
uma e onde assistir. Depois disso você pode:

- **Refinar o pedido:** "mais curto", "algo brasileiro", "esse já vimos".
- **Guardar para ver:** adicione à watchlist no Letterboxd; ela entra aqui no próximo export.
- **Contar o que achou:** diga "assisti o X, gostei"; o Claude Code oferece registrar o feedback.
  "Registre que gostei de X" já autoriza o registro, sem confirmação adicional.

As regras permanentes estão em [CLAUDE.md](CLAUDE.md), e o roteiro na
[skill filme](.claude/skills/filme/SKILL.md). Em uma nova sessão, o feedback continua nos arquivos;
os filtros de uma conversa anterior precisam ser informados novamente.

Em refinamentos, o Claude Code mantém as restrições anteriores. Se faltarem resultados, apresenta os encontrados
e propõe uma mudança de filtro para você escolher. Exclusões por tema dependem das keywords e não garantem
ausência do conteúdo. Pedir algo para casal usa seu perfil existente, sem combinar dois históricos.

Disponibilidade é informação de saída por padrão: "hoje/agora" não restringe a serviços. Pedidos amplos
("me recomende um filme", "cinema japonês", "me surpreenda") usam `recs explore --json` e consideram
filmes sem streaming conhecido. Somente pedidos como "nos meus streamings" ativam o filtro correspondente.

### Direto no terminal

```powershell
uv run recs now -g comedia -g crime --all-genres --subscribed-only
uv run recs now -g terror --years 1970s --streaming-only
uv run recs now -g comedia --max-runtime 110 --subscribed-only `
    --prefer lighthearted,feelgood --avoid gore,rape,torture,suicide
```

| opção | o que faz |
|---|---|
| `-g, --genre` | gênero em português ou inglês: comedia, crime/policial, drama, terror, suspense, romance, animacao, documentario, acao, aventura, ficcao, fantasia, misterio, guerra, faroeste, musica, historia, familia. Vários `-g` aceitam **qualquer um** dos gêneros. |
| `--all-genres` | exige **todos** os gêneros (comédia **e** policial) |
| `--max-runtime`, `--min-runtime` | duração em minutos |
| `--subscribed-only` | só filmes nos serviços assinados (`config.toml → provedores_assinados`) |
| `--streaming-only` | só filmes em streaming no BR, em qualquer serviço |
| `--provider Netflix` | só neste serviço; repita para aceitar qualquer um dos serviços indicados |
| `--country BR`, `--language ja` | país de produção ou idioma original |
| `--years` | `1990s`, `90s`, `1980-2000`, `2010-`, `-1979` |
| `--prefer` | keywords do TMDB (nome exato, em inglês) que sobem o filme no ranking (+25% cada) |
| `--avoid` | termos que eliminam o filme: `gore` elimina também "extreme gore" |
| `--exclude` | ids TMDB que ficam de fora só nesta consulta |
| `--n` | quantos filmes mostrar (padrão 8) |
| `--markdown caminho.md` | grava as indicações em Markdown (nunca sobrescreve; ver seção 4) |
| `--json` | saída estruturada para o agente; disponível também em `keywords` e `feedback` |

Para descobrir o nome exato de uma keyword:

```powershell
uv run recs keywords comedy
#   172  dark comedy
#    29  sex comedy
#    22  buddy comedy ...
```

## 2. Lista "para ver"

A lista "para ver" é a watchlist do Letterboxd. Para guardar um filme, adicione-o lá; ele entra aqui no próximo
export manual (seção 5), como candidato sempre presente e com multiplicador no score (📌 no relatório).
Não há lista de salvos local.

## 3. Dizer o que achou

```powershell
uv run recs feedback 11300 bom     # gostei: entra no perfil com peso positivo
uv run recs feedback 605 nao       # não quero: sai das sugestões
uv run recs feedback 155 ja_vi     # já vi (fora do Letterboxd): sai das sugestões
```

- O feedback fica em `overrides/feedback.csv`.
- Vale o último veredito de cada filme.
- Novos nomes: `liked` (alias `bom`), `disliked`, `not_interested` (alias `nao`), `already_seen` (alias `ja_vi`).
  `liked` preserva o peso positivo existente e indica assistido; `disliked` não aprende peso negativo ainda.
- `not_now --interaction <id>` registra exclusão apenas contextual, sem CSV permanente. Acumule os IDs
  retornados em `--exclude` no refinamento. Consultas independentes não herdam essa exclusão.
- `feedback` aceita `--interaction <id>` para relacionar a ação à consulta que apresentou o filme.
  `recs interaction <id> --json` consulta o registro. Não há aprendizado automático das interações.
- O feedback complementa o Letterboxd: avaliar e registrar o filme lá continua sendo o sinal mais forte, porque
  entra no próximo export.

## 4. Relatório completo

```powershell
uv run recs explore -g comedia --n 5 --markdown reports/2026-10-09-comedias.md --json
uv run recs explore --json       # sem --markdown: nenhum arquivo
uv run recs recommend            # atalho: 20 filmes em reports/AAAA-MM-DD.md
```

Pelo Claude Code, toda busca grava o relatório em `reports/AAAA-MM-DD-<slug>.md`. Um arquivo existente nunca é
sobrescrito (o próximo vira `-2`, `-3`), então dá para editar, anotar e revisar com o agente. Cada relatório traz:

- o contexto, o `interaction_id` e o tamanho do pool;
- por filme: título em português com o original, ano, diretor, duração, gêneros e países;
- onde assistir, com os serviços assinados em negrito, ou "sem dado de disponibilidade";
- os três principais motivos, score pessoal, score e link para o TMDB;
- o bloco "De outros lugares" (complementos de origem), avisos e uma seção `## Notas` livre.

A marca no título é 📌 para watchlist. A disponibilidade é a do dia da busca.

O `recs match` não gera relatório datado: grava `reports/revisao-match.md` só quando há ambíguos ou não
resolvidos, e apaga o arquivo quando não há pendências.

## 5. Atualizar com um novo export do Letterboxd

1. No Letterboxd, vá em *Settings → Import & Export → Export your data* e baixe o ZIP.
2. Rode:

   ```powershell
   uv run recs ingest ..\letterboxd-<usuario>-<data>.zip
   uv run recs match       # só busca os filmes novos; o resto vem do cache
   uv run recs enrich
   uv run recs movielens data/movielens/ml-32m   # recalcula vizinhos dos filmes novos (~20 s)
   uv run recs recommend
   ```

3. Se o `match` listar filmes não resolvidos, corrija em `overrides/matches.csv`:

   ```csv
   lb_uri,name,year,tmdb_id,note
   https://boxd.it/i3RC,Marighella,2019,500458,TMDB data como 2021
   ,House of Cards,1990,,série de TV
   ```

   Um `tmdb_id` vazio faz o filme ser ignorado (útil para séries e episódios). `note` é livre.

   O id TMDB é o número na URL `themoviedb.org/movie/<id>`. Rode `recs match` de novo depois de corrigir.

## 6. Ajustar o comportamento

Tudo fica em `config.toml`. Os ajustes mais comuns:

| chave | efeito |
|---|---|
| `availability.provedores_assinados` | seus serviços. Use os nomes como o JustWatch mostra; canais Amazon contam à parte. |
| `availability.batch_size`, `max_candidates` | tamanho do lote e orçamento de verificação quando streaming é obrigatório |
| `retrieval.profile_discover_features`, `profile_discover_min_evidence` | expansão geral por features positivas do perfil; zero features desativa |
| `score.popularity_alpha` | 0,08 hoje. Valor maior traz filmes menos conhecidos; menor traz mais populares. |
| `score.include_documentaries`, `include_shorts` | incluir documentários ou curtas |
| `score.max_per_director` | máximo de filmes do mesmo diretor por lista |
| `profile.feature_weights` | quanto pesam diretor, roteiro, fotografia, país, keywords etc. |
| `now.prefer_bonus` | quanto cada keyword do `--prefer` sobe o filme |

Antes de mudar um peso, compare a mudança com a linha de base em uma cópia isolada do projeto e dos dados:

```powershell
uv run recs eval --set score.popularity_alpha=0.12 --vs "baseline-v2 alpha 0.08"
```

O eval pode buscar dados na rede e deixa as tabelas derivadas no estado do último seed. "Offline" descreve
o método de avaliação, não uma garantia de execução sem rede. Na cópia, rode `recs recommend` para reconstruir
as tabelas depois. Compare execuções com o mesmo histórico, configuração de avaliação e cache.

O eval mostra:

- **recall de candidatos:** fração dos filmes escondidos que voltaram como candidatos;
- **hit@20 e hit@50:** fração que apareceu entre as 20 ou 50 primeiras sugestões;
- **votos top 20:** mediana de votos no TMDB das 20 primeiras sugestões, ou seja, quão conhecidas elas são.
- **NDCG@20, MRR@50:** qualidade da ordem com relevância binária do holdout.
- **diversidade de diretores:** distância média entre os conjuntos de diretores; nulo se faltarem dados.

Cada linha traz média ± desvio entre os seeds configurados e o Δ em relação à execução comparada.
`hit@20` e `hit@50` são recall em K. Com poucos filmes escondidos, diferenças pequenas exigem cautela;
um limiar fixo de 5 pontos não demonstra significância. Avalie também diversidade e restrições antes de
adotar pesos. Se compensar, edite o `config.toml` e rode `recs eval --label <nome>` na cópia para fixar a referência.

## 7. Outros comandos

| comando | para quê |
|---|---|
| `recs profile [-t director -t keyword] [--n 15]` | ver o perfil de gosto: features que mais puxam para cima e para baixo, com os filmes responsáveis |
| `recs profile --json` | afinidades, IDs, quantidade de evidências, notas e pesos dos filmes responsáveis |
| `recs keywords <termo>` | buscar nomes de keyword |
| `recs eval [--set k=v] [--vs rótulo] [--label nome]` | avaliação offline |

## Problemas comuns

- **`TMDB_API_KEY ausente`:** crie o `.env` (veja o README).
- **Um filme que você assina aparece como "outro streaming":** confira o nome exato em `recs now --json`
  (campo `streaming`) e ajuste `provedores_assinados`.
- **Poucos resultados no `now`:** o comando avisa. Você pode escolher ampliar duração, serviços ou gêneros;
  o Claude Code preserva as restrições até essa escolha. `diagnostico.availability.stop_reason` distingue pool
  esgotado de orçamento atingido (`limit`). O orçamento só existe quando streaming é obrigatório.
- **Disponibilidade desatualizada:** os provedores ficam 7 dias em cache, e os metadados 90 dias
  (`[tmdb]` no config).

Dados de filmes: TMDB. Dados de streaming: JustWatch.
