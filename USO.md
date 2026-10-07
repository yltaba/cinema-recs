# Como usar

Todos os comandos rodam de dentro da pasta `cinema-recs` com `uv run recs <comando>`. `--help` mostra as opções
de cada um.

## 1. Pedir um filme para agora

### Pelo Codex (recomendado)

Abra o projeto `cinema-recs` no Codex e peça em linguagem natural (ou invoque `$filme`):

> estou com minha namorada e queremos ver algo engraçado, nada pesado, até umas 2h
>
> quero ver uma comédia policial
>
> algum terror dos anos 70, qualquer streaming serve

O Codex transforma o pedido num `recs now --json`, roda o comando e apresenta de 3 a 5 opções, se disponíveis, com o motivo de cada
uma e onde assistir. Depois disso você pode:

- **Refinar o pedido:** "mais curto", "algo brasileiro", "esse já vimos".
- **Salvar sugestões:** "salve essas".
- **Contar o que achou:** diga "assisti o X, gostei"; o Codex oferece registrar o feedback.
  "Registre que gostei de X" já autoriza o registro, sem confirmação adicional.

As regras permanentes estão em [AGENTS.md](AGENTS.md), e o roteiro na
[skill filme](.agents/skills/filme/SKILL.md). Em uma nova sessão, salvos e feedback continuam nos arquivos;
os filtros de uma conversa anterior precisam ser informados novamente.

Em refinamentos, o Codex mantém as restrições anteriores. Se faltarem resultados, apresenta os encontrados
e propõe uma mudança de filtro para você escolher. Exclusões por tema dependem das keywords e não garantem
ausência do conteúdo. Pedir algo para casal usa seu perfil existente, sem combinar dois históricos.

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
| `--country BR`, `--language ja` | país de produção ou idioma original |
| `--years` | `1990s`, `90s`, `1980-2000`, `2010-`, `-1979` |
| `--prefer` | keywords do TMDB (nome exato, em inglês) que sobem o filme no ranking (+25% cada) |
| `--avoid` | termos que eliminam o filme: `gore` elimina também "extreme gore" |
| `--exclude` | ids TMDB que ficam de fora só nesta consulta |
| `--n` | quantos filmes mostrar (padrão 8) |
| `--json` | saída estruturada para o Codex; disponível também em `keywords`, `salvar`, `salvos` e `feedback` |

Para descobrir o nome exato de uma keyword:

```powershell
uv run recs keywords comedy
#   172  dark comedy
#    29  sex comedy
#    22  buddy comedy ...
```

## 2. Lista "para ver"

```powershell
uv run recs salvar 856 9430 --contexto "comédia policial"   # guarda os filmes (ids da coluna tmdb)
uv run recs salvos                                         # pendentes, com onde assistir hoje
```

- Os salvos ficam em `overrides/salvos.csv`.
- A CLI inclui salvos no pool, com o mesmo multiplicador da watchlist (🔖 no relatório).
  Ao pedir opções novas na conversa, o Codex os exclui daquela consulta; você pode pedir para reconsiderá-los.
- Saem da lista de pendentes quando você os marca com `feedback` ou quando aparecem como vistos num novo export.

## 3. Dizer o que achou

```powershell
uv run recs feedback 11300 bom     # gostei: entra no perfil com peso positivo
uv run recs feedback 605 nao       # não quero: sai das sugestões
uv run recs feedback 155 ja_vi     # já vi (fora do Letterboxd): sai das sugestões
```

- O feedback fica em `overrides/feedback.csv`.
- Vale o último veredito de cada filme.
- O feedback complementa o Letterboxd: avaliar e registrar o filme lá continua sendo o sinal mais forte, porque
  entra no próximo export.

## 4. Relatório completo

```powershell
uv run recs recommend            # 20 por lista; --n 30 para mais
```

O relatório é gravado em `reports/AAAA-MM-DD.md` e traz, para cada filme:

- o id TMDB;
- o título em português, com o original entre parênteses;
- os três principais motivos (por exemplo "diretor: Luis Buñuel · idioma: French");
- onde assistir, com os serviços assinados em negrito.

As marcas no título são 📌 para watchlist e 🔖 para salvo.

## 5. Atualizar com um novo export do Letterboxd

1. No Letterboxd, vá em *Settings → Import & Export → Export your data* e baixe o ZIP.
2. Rode:

   ```powershell
   uv run recs ingest ..\letterboxd-<usuario>-<data>.zip
   uv run recs match       # só busca os filmes novos; o resto vem do cache
   uv run recs enrich
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

Cada linha traz média ± desvio entre os seeds configurados e o Δ em relação à execução comparada.
`hit@20` e `hit@50` são recall em K. Com poucos filmes escondidos, diferenças pequenas exigem cautela;
um limiar fixo de 5 pontos não demonstra significância. Avalie também diversidade e restrições antes de
adotar pesos. Se compensar, edite o `config.toml` e rode `recs eval --label <nome>` na cópia para fixar a referência.

## 7. Outros comandos

| comando | para quê |
|---|---|
| `recs profile [-t director -t keyword] [--n 15]` | ver o perfil de gosto: features que mais puxam para cima e para baixo, com os filmes responsáveis |
| `recs keywords <termo>` | buscar nomes de keyword |
| `recs eval [--set k=v] [--vs rótulo] [--label nome]` | avaliação offline |

## Problemas comuns

- **`TMDB_API_KEY ausente`:** crie o `.env` (veja o README).
- **Um filme que você assina aparece como "outro streaming":** confira o nome exato em `recs now --json`
  (campo `streaming`) e ajuste `provedores_assinados`.
- **Poucos resultados no `now`:** o comando avisa. Você pode escolher ampliar duração, serviços ou gêneros;
  o Codex preserva as restrições até essa escolha. A busca atual também limita candidatos antes de verificar disponibilidade.
- **Disponibilidade desatualizada:** os provedores ficam 7 dias em cache, e os metadados 90 dias
  (`[tmdb]` no config).

Dados de filmes: TMDB. Dados de streaming: JustWatch.
