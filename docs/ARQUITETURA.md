# Arquitetura

O sistema é um pipeline em fases. Todas gravam num único banco DuckDB (`data/recs.duckdb`), e as tabelas
derivadas são recriadas por SQL a partir do JSON bruto. Isso torna barato refazer qualquer etapa.

| módulo | papel |
|---|---|
| `ingest.py` | lê os CSVs do export → `lb_films` |
| `match.py` | Letterboxd → `tmdb_id` → `film_map` |
| `tmdb.py` | cliente HTTP assíncrono com cache, limite de concorrência e backoff |
| `enrich.py` | baixa `/movie/{id}` → `tmdb_raw` e deriva as tabelas `film_*` |
| `profile.py` | `film_features`, `profile_films`, `profile_features` |
| `candidates.py` | gera o pool de candidatos → `candidates` |
| `score.py` | `contributions`, `scores`, ranking, motivos e diversidade |
| `availability.py` | provedores no BR e classificação disponível × explorar |
| `context.py` | modo `now`: filtros, `/discover` e bônus por keyword |
| `saved.py` | lista local de salvos |
| `evaluate.py` | eval offline por holdout → `eval_runs` |
| `report.py` | relatório Markdown |
| `cli.py` | comandos typer |

## Fase 1 — ingestão e matching

**Ingestão.** `watched.csv`, `ratings.csv`, `watchlist.csv` e `likes/films.csv` são chaveados pela URI do filme
(`boxd.it/...`). Em `diary.csv` e `reviews.csv` a URI aponta para a *entrada do diário*, não para o filme, por
isso esses dois arquivos entram por (nome, ano).

**Matching.** A busca no TMDB usa `language=en-US`, porque os nomes do export vêm em inglês. Os títulos são
normalizados com unidecode, caixa baixa, `&`→and, sem pontuação e sem artigo inicial em várias línguas. A
resolução segue nesta ordem:

1. **Estrita:** título normalizado idêntico e ano ±1. Remakes desempatam pelo ano. Num empate no mesmo ano, vence
   o filme com muito mais votos (≥ 5× e +50); sem isso, a confiança fica em 0,85 e o match é marcado como ambíguo.
2. **Busca ampliada:** `primary_release_year` ±1, sem ano e com o prefixo antes de `:` ou `,`.
3. **Fuzzy:** `0,7·título + 0,3·ano`, aceito com score ≥ 0,85 e margem ≥ 0,03 sobre o segundo colocado.
4. **Overrides:** `overrides/matches.csv` sempre vence.

Os casos não resolvidos vão para `overrides/unmatched.csv`.

## Fase 2 — enriquecimento

Cada filme custa uma chamada `/movie/{id}`, com `append_to_response=credits,keywords,recommendations,similar,
watch/providers,translations` em `en-US`. Em inglês, os nomes de pessoas vêm romanizados ("Fruit Chan", não
"陳果"); o título em português vem de `translations`.

Antes de gravar, `slim()` corta do payload:

- provedores de outras regiões;
- traduções em outras línguas;
- a equipe fora dos papéis usados;
- o elenco além do 10º nome.

Com isso o payload cai de ~115 KB para ~11 KB.

| cache | validade |
|---|---|
| metadados | 90 dias |
| provedores | 7 dias |
| buscas e filmografias | 90 dias, em `http_cache` |

O cliente usa 20 requisições simultâneas e faz backoff exponencial em 429/5xx, respeitando `Retry-After`.

As tabelas derivadas são `film_meta`, `film_genres`, `film_keywords`, `film_countries`, `film_languages`,
`film_people` (diretor, roteiro, fotografia, montagem, trilha) e `film_links`.

## Fase 3 — perfil de gosto

O peso de cada filme visto é:

```
w(filme) = nota − média_do_usuário
```

- Filmes sem nota recebem 0,1.
- Um like soma +0,2.
- Feedback `bom` dá 0,3 (para filmes não vistos no Letterboxd).

A afinidade de cada feature (diretor, roteirista, fotógrafo, montador, compositor, país, idioma original,
década, keyword, gênero) é:

```
afinidade(feature) = Σ w / (n + k)        k = 2 (shrinkage: poucos filmes puxam para 0)
keywords: × ln(N/df) / ln(N)              (idf normalizado: keyword presente em tudo vale 0)
```

## Fase 4 — candidatos, score e disponibilidade

**Fontes de candidatos**, com dedup e sem filmes já vistos ou com feedback `nao`/`ja_vi`:

1. `recommendations` e `similar` dos filmes com nota ≥ 4 (já estão no payload);
2. filmografias dos 25 diretores, 10 fotógrafos e 10 roteiristas com maior afinidade;
3. watchlist do Letterboxd e salvos, que são isentos dos filtros;
4. `seeds/*.csv`, também isentos.

Um pré-filtro barato (votos ≥ 20, já lançado) evita enriquecer filmes que seriam descartados.

**Score:**

```
base  = Σ_tipo peso_tipo × agg(afinidade)      agg = soma para keywords; média no filme para os outros tipos
score = base × 1/(1 + α·ln(1 + votos)) × boost  α = 0,08; boost = 1,3 para watchlist/salvos
```

Pessoas, país e idioma entram pela média no filme para que uma antologia com 20 diretores não some 20
afinidades.

Filtros: votos ≥ 20 e duração ≥ 60 min (curtas ficam fora por configuração). Na lista final, entram no máximo 2
filmes por diretor.

**Disponibilidade.** Os dados do JustWatch vêm via TMDB, região BR:

- **streaming:** `flatrate`, `free` ou `ads`;
- **aluguel/compra:** `rent` ou `buy`.

O sufixo de plano com anúncios é removido ("Netflix Standard with Ads" → Netflix). Canais ("HBO Max Amazon
Channel") **não** contam como o serviço assinado, porque são assinaturas à parte.

## Fase 6 — eval offline

Para cada seed (1 a 5), o eval:

1. esconde 15% dos filmes com nota ≥ 4,5;
2. refaz perfil, candidatos e score como se eles não tivessem sido vistos, sem usar o feedback;
3. mede:
   - **recall de candidatos:** a fração dos escondidos que voltou ao pool;
   - **hit@20 e hit@50:** a fração no top k depois do limite por diretor;
   - **votos top 20:** a mediana de votos do top 20.

O resultado vai para `eval_runs` com o config usado. `--set` testa uma mudança sem editar o arquivo, e `--vs`
compara com uma execução rotulada.

Limitação conhecida: os filmes que o usuário já amou tendem a ser populares, então o eval favorece rankings
mainstream. O α é uma escolha de gosto (hoje "meio a meio"), não algo para maximizar no eval.

Linha de base (`baseline-v2 alpha 0.08`):

| métrica | valor |
|---|---|
| recall de candidatos | 37% |
| hit@20 | 3,8% |
| hit@50 | 6,7% |
| votos top 20 | 640 |

O gargalo é o pool: as `recommendations` do TMDB não alcançam vários clássicos.

## Fase 7 — modo contexto

Em `recs now`, o pool da Fase 4 ganha resultados de `/discover/movie` com os mesmos filtros: gênero, duração,
idioma, país, anos e provedores assinados. São duas ordenações, nota média (com piso de 300 votos) e
popularidade, até 3 páginas cada, com cache de 7 dias.

Depois do score normal:

- gênero, duração, idioma, país, anos e keywords evitadas atuam como **filtros rígidos**;
- cada keyword preferida presente multiplica o score positivo por 1,25.

A disponibilidade é consultada só para o topo.

O `CLAUDE.md` descreve como o Claude Code traduz pedidos em linguagem natural para essas flags. A interpretação
fica com o modelo, e o `recs` continua determinístico e testável.

Pendente: perfil de casal a partir de um segundo export. A afinidade de cada filme seria o mínimo dos dois
perfis, e sairia o que qualquer um dos dois já viu.

## Tabelas

| tabela | conteúdo |
|---|---|
| `lb_films` | um filme do export: nota, visto, watchlist, like, resenha, última data |
| `film_map` | `lb_uri → tmdb_id`, método e confiança |
| `tmdb_raw` | payload enxuto do TMDB por filme |
| `http_cache` | respostas de busca, filmografias, provedores e discover |
| `film_*` | tabelas derivadas do `tmdb_raw` |
| `film_features` | (filme, tipo, id, rótulo) |
| `profile_films`, `profile_features` | perfil de gosto |
| `candidates`, `contributions`, `scores` | última execução do ranking |
| `eval_runs` | histórico de avaliações |

## Desempenho

Com 711 filmes vistos e ~4.700 candidatos:

- `recommend` e `now` levam 3–4 s com o cache quente, sem requisições;
- `eval` leva ~10–60 s, dependendo de quantas filmografias novas o perfil reduzido pede.

Uma armadilha do DuckDB: `executemany` e listas Python grandes como parâmetro são muito lentos, porque ele tenta
importar numpy/pandas a cada valor. Para inserções em lote, passe um único JSON e use
`unnest(json_extract(?::JSON, '$[*]'))`.
