# Arquitetura

O sistema é um pipeline em fases. Todas gravam num único banco DuckDB (`data/recs.duckdb`), e as tabelas
derivadas são recriadas por SQL a partir do JSON bruto. Isso torna barato refazer qualquer etapa.

O Claude Code opera a CLI e interpreta pedidos. O Python executa deterministicamente:
`retrieval → eligibility/context filters → personal score → contextual rerank → availability → presentation`.
Disponibilidade é metadado por padrão; somente flags explícitas ativam seu filtro. "Hoje/agora" não é uma flag.

| módulo | papel |
|---|---|
| `ingest.py` | lê os CSVs do export → `lb_films` |
| `match.py` | Letterboxd → `tmdb_id` → `film_map` |
| `tmdb.py` | cliente HTTP assíncrono com cache, limite de concorrência e backoff |
| `enrich.py` | baixa `/movie/{id}` → `tmdb_raw` e deriva as tabelas `film_*` |
| `profile.py` | `film_features`, `profile_films`, `profile_features` |
| `candidates.py` | gera o pool de candidatos → `candidates` |
| `movielens.py` | vizinhos colaborativos do MovieLens → `ml_neighbors` |
| `eligibility.py` | elegibilidade global independente de score e catálogo |
| `score.py` | afinidade pessoal, componentes legados do ranking, motivos e diversidade |
| `availability.py` | metadados de provedores; filtro explícito com verificação progressiva |
| `context.py` | filtros estruturados, discover contextual e bônus por keyword |
| `pipeline.py` | orquestra a consulta compartilhada por now/explore/recommend; diagnósticos |
| `feedback.py` | vocabulário canônico, aliases e CSV persistente |
| `interactions.py` | consultas e ações locais identificadas, sem aprendizado automático |
| `evaluate.py` | eval offline por holdout → `eval_runs` |
| `report.py` | indicações em Markdown e revisão do matching |
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
- Feedback `liked` (alias `bom`) dá 0,3 para filmes não vistos no Letterboxd.
- `disliked` é registrado, mas não recebe peso negativo inventado. `not_interested` não representa gosto.
- Perfil com apenas um filme usa IDF de keyword zero, evitando o caso indefinido `0/0`.

A afinidade de cada feature (diretor, roteirista, fotógrafo, montador, compositor, país, idioma original,
década, keyword, gênero) é:

```
afinidade(feature) = Σ w / (n + k)        k = 2 (shrinkage: poucos filmes puxam para 0)
keywords: × ln(N/df) / ln(N)              (idf normalizado: keyword presente em tudo vale 0)
```

## Fase 4 — candidatos, score e disponibilidade

**Fontes de candidatos**, com dedup e sem filmes vistos ou com feedback persistente:

1. `recommendations` e `similar` dos filmes com nota ≥ 4 (já estão no payload);
2. filmografias dos 25 diretores, 10 fotógrafos e 10 roteiristas com maior afinidade;
3. watchlist do Letterboxd, que é isenta dos filtros;
4. `seeds/*.csv`, também isentos.
5. vizinhos colaborativos do MovieLens (`movielens`): os `candidates.movielens_per_seed` (20) mais próximos de
   cada filme com nota ≥ 4, sem pré-filtro (a elegibilidade decide após o enriquecimento);
6. discover geral, com até três features positivas de país/idioma/gênero com pelo menos dois filmes
   de evidência; se não houver, discover geral sem feature. Configurável em `[retrieval]`.

As consultas por feature se unem ao pool, não filtram suas outras fontes. Todas as origens sobrevivem à
deduplicação em `candidates.sources`, aparecem em `fontes` e nas contagens `retrieval_sources` do JSON.
Discover geral nunca recebe catálogo ou provedores. Também é usado pelo eval.

Um pré-filtro barato (votos ≥ 20, já lançado) evita enriquecer filmes que seriam descartados.

**Score:**

```
base  = Σ_tipo peso_tipo × agg(afinidade)      agg = soma para keywords; média no filme para os outros tipos
base += β × Σ_filmes_do_perfil w × cos_MovieLens   β = score.movielens_weight = 0,25
score = base × 1/(1 + α·ln(1 + votos)) × boost  α = 0,08; boost = 1,3 para watchlist
```

**Sinal colaborativo.** `recs movielens <pasta>` lê `ratings.csv` e `links.csv` do MovieLens 32M (GroupLens, ratings
até 2023) e grava `ml_neighbors (tmdb_id, neighbor_id, score, support)` para os filmes vistos. "Gostar" é nota ≥ 4.
Para cada filme visto, amostra até 2.000 usuários que gostaram dele (ordem por hash, determinística) e estima o
cosseno binário `co·n_X/n_amostra / sqrt(n_X·n_Y)`, com suporte ≥ 5 e vizinho com ≥ 50 "gostei"; guarda 50 vizinhos.
No score, cada filme do perfil contribui `β × w × cos` aos seus vizinhos (motivo "quem gostou de: X"). Como usa
`profile_films`, o holdout do eval nunca contribui. Sem a tabela, fonte e sinal ficam inertes. Recalcule após cada
novo export. Dos 527 vistos em 09/10/2026, 441 estão no MovieLens e 406 têm vizinhos.

Pessoas, país e idioma entram pela média no filme para que uma antologia com 20 diretores não some 20
afinidades.

`score_pessoal` expõe `base`: somente afinidades do histórico. `score` mantém a fórmula legada para
compatibilidade; `ajustes` expõe popularidade e boost. Nenhum desses campos inclui disponibilidade.
`score_contexto = score × (1 + prefer_bonus × número de keywords preferidas)` para score positivo;
scores não positivos permanecem iguais. Empates usam ID TMDB. Pesos não foram alterados nesta reforma.

Filtros: votos ≥ 20 e duração ≥ 60 min (curtas ficam fora por configuração). Na lista final, entram no máximo 2
filmes por diretor.

**Disponibilidade.** Os dados do JustWatch vêm via TMDB, região BR:

- **streaming:** `flatrate`, `free` ou `ads`;
- **aluguel/compra:** `rent` ou `buy`.

Sem restrição, diversidade e seleção precedem a consulta de provedores, apenas para os filmes retornados.
Com `--streaming-only`, `--subscribed-only` ou `--provider`, percorre-se o ranking em lotes até preencher N respeitando
diversidade, esgotar o pool ou atingir `availability.max_candidates`. `batch_size` limita cada lote.
`disponibilidade_conhecida=false` não penaliza nem exclui filmes nas consultas sem restrição.
`stop_reason` distingue `filled`, `exhausted` e `limit`; este último produz aviso de candidatos não verificados.
`--provider Netflix` aplica filtro determinístico pelo nome normalizado do serviço, sem equiparar canais
adicionais à assinatura principal. Vários provedores são alternativas; junto de `--subscribed-only`, o
provedor correspondente também precisa ser assinado. O agente não filtra manualmente a saída.

Equilíbrio de origem: sem `--country`/`--language`, se um país passa de `score.max_country_share` (0,4) na
seleção, `diversify` mantém a seleção principal e acrescenta complementos de outros países, na ordem do ranking
e respeitando o limite por diretor, até o teto ou 2n itens (`complemento_origem: true`). Coproduções contam
para cada país. Com streaming obrigatório, o teto vale sobre os aceitos, e os lotes continuam até equilibrar
ou esgotar o orçamento. Scores e ordem não mudam. `diagnostico.availability.origem` registra teto, país
dominante, participação e complementos. Na descoberta por perfil, país e idioma correspondentes (`JP`/`ja`)
ocupam um único slot.

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
   - **NDCG@20 e MRR@50:** relevância binária do holdout (todos os escondidos são relevantes).
   - **diversidade de diretores no top 20:** distância média de Jaccard entre pares com diretores conhecidos;
     sem dois filmes com dados, o resultado é nulo, não zero.

O resultado vai para `eval_runs` com o config usado. Colunas novas são adicionadas idempotentemente;
avaliações antigas têm métricas novas nulas, sem inventar comparativos. `--set` testa uma mudança sem editar o arquivo, e `--vs`
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

O gargalo era o pool: as `recommendations` do TMDB não alcançam vários clássicos.

Comparativo MovieLens (09/10/2026, export atual com 527 vistos, cópia isolada, 5 seeds, holdout 15%):

| variante | recall cand. | hit@20 | hit@50 | NDCG@20 | votos top 20 | país top 20 |
|---|---|---|---|---|---|---|
| sem MovieLens (`ml-off`) | 44,8% | 1,0% | 1,0% | 0,007 | 725 | 0,28 |
| só candidatos (20 por filme, β = 0) | 73,3% | 1,0% | 1,0% | 0,007 | 725 | 0,28 |
| β = 0,1 | 73,3% | 1,9% | 3,8% | 0,014 | 1.125 | 0,30 |
| **β = 0,25 (ativo)** | 73,3% | 6,7% | 9,5% | 0,058 | 1.706 | 0,38 |
| β = 0,5 | 73,3% | 7,6% | 17,1% | 0,114 | 4.432 | 0,52 |
| β = 1 | 73,3% | 15,2% | 23,8% | 0,171 | 13.791 | 0,80 |
| β = 3 | 73,3% | 17,1% | 25,7% | 0,183 | 15.295 | 0,91 |

Só ampliar o pool não muda o top: os filmes recuperados ficavam entre as posições 100 e 4.000, porque o score
de conteúdo não os distingue. O ganho vem do sinal no score. Pesos altos maximizam o eval à custa de um ranking
mainstream e concentrado num país (o viés conhecido do holdout); β = 0,25 foi escolhido por gosto, como o α.

## Fase 7 — modo contexto

Em `recs now` e `recs explore`, o pool geral ganha resultados de `/discover/movie` com filtros contextuais:
gênero, duração, idioma, país e anos; provedores somente com restrição explícita. São duas ordenações, nota média (com piso de 300 votos) e
popularidade, até 3 páginas cada. O TTL depende da presença de restrição de disponibilidade.

O pipeline separa filtros de pontuação:

- gênero, duração, idioma, país, anos e keywords evitadas atuam como **filtros rígidos**;
- keywords preferidas aplicam a fórmula aditiva de bônus descrita acima.

Cache de discover usa TTL de buscas sem streaming e TTL de provedores quando depende de disponibilidade.
Não há mais corte em 3.000 scores nem corte prévio em 200 candidatos. Há orçamento somente para a
verificação de disponibilidade obrigatória. Diagnósticos incluem contagens cumulativas por filtro.

O `CLAUDE.md` contém as regras permanentes do Claude Code; `.claude/skills/filme/SKILL.md` contém o roteiro de
tradução de pedidos para flags, refinamentos e feedback. A interpretação fica com o modelo,
e o `recs` continua determinístico e testável. Não há chamada a modelo de linguagem no pipeline Python.

`now`, `explore`, `profile`, `interaction`, `keywords` e `feedback` aceitam `--json`, com `schema_version: 1` nas respostas de
sucesso. Os campos existentes de `now` foram preservados. Histórico do contrato em `historico/MIGRACAO-CODEX.md`.
Erros ainda usam código de saída não zero e stderr, sem contrato JSON unificado.

Perfil de casal está fora do escopo: somente reconsiderar com segundo histórico real e uso recorrente.
`recommend` é compatibilidade para exploração com relatório. `explore --markdown caminho.md` grava as
indicações em Markdown; o Claude Code usa esse arquivo em toda busca (`reports/AAAA-MM-DD-<slug>.md`), e o JSON
continua sendo a interface. `write_explore` nunca sobrescreve: um caminho existente vira `-2`, `-3`, e o caminho
efetivo sai em `relatorio`. `recs match` grava `reports/revisao-match.md` só com ambíguos ou não resolvidos.

## Interações e feedback

Cada consulta concluída registra contexto estruturado, opções emitidas pela CLI, ranks, scores, fontes e
configuração sem credenciais em `interactions`. Isso mede exposição pela CLI, não confirma visualização ou
reprodução pelo usuário. `--interaction` associa explicitamente ações posteriores; não se presume a última
consulta. Ações sem associação são registradas com ID nulo. Os registros não alimentam perfil ou ranking.

Avaliações privadas (`recs rate`, `ratings.py`) ficam em `overrides/avaliacoes.csv` (`tmdb_id,titulo,nota,like,
critica,data,interaction_id`; fora do Git). A última linha por filme prevalece. Para filmes ausentes do export,
`profile.build(ratings=...)` aplica `w = nota − média_Letterboxd (+ liked_bonus)`; se o filme está no export,
o Letterboxd prevalece. Todo filme avaliado sai das sugestões (`pipeline.query`). A crítica não influencia o ranking.

CSV antigo é normalizado apenas na leitura (`bom → liked`, `nao → not_interested`, `ja_vi → already_seen`).
O último feedback persistente prevalece. `liked`, `disliked` e `already_seen` indicam visto; `not_interested`
exclui sem avaliar gosto. `not_now` exige interação e só registra ação contextual, retornando `exclude` para
o próximo refinamento. Não entra no CSV nem altera futuras consultas independentes.

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
| `ml_neighbors` | vizinhos colaborativos do MovieLens dos filmes vistos |
| `eval_runs` | histórico de avaliações |
| `interactions`, `interaction_actions` | instrumentação local aditiva, sem aprendizado |

## Desempenho

Medições históricas anteriores à reforma (não revalidadas para discover ampliado e instrumentação):

Com 711 filmes vistos e ~4.700 candidatos:

- `recommend` e `now` levam 3–4 s com o cache quente, sem requisições;
- `eval` leva ~10–60 s, dependendo de quantas filmografias novas o perfil reduzido pede.

Uma armadilha do DuckDB: `executemany` e listas Python grandes como parâmetro são muito lentos, porque ele tenta
importar numpy/pandas a cada valor. Para inserções em lote, passe um único JSON e use
`unnest(json_extract(?::JSON, '$[*]'))`.
