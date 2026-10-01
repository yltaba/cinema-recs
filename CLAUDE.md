# cinema-recs

Recomendador pessoal de filmes: export do Letterboxd → TMDB → sugestões com disponibilidade no Brasil.
Status das fases e decisões em `PLANO.md`.

## Regras fixas

- Nunca fazer requisições ao letterboxd.com (nem scraping, nem RSS). A única entrada é o ZIP exportado.
- Segredos só em `.env` (pasta acima do projeto). Nunca imprimir a chave.
- Pesos e limites em `config.toml` só mudam com um `uv run recs eval --set ... --vs <rótulo>` comparativo.
- Toda lista de filmes mostrada ao usuário termina com "Dados de filmes: TMDB. Dados de streaming: JustWatch."

## Pedidos de filme para agora ("estou com minha namorada e queremos ver algo engraçado")

1. Traduza o pedido em flags de `uv run recs now ... --json`. Use só o que o pedido justifica:

   | o pedido diz | flag |
   |---|---|
   | engraçado, comédia, para rir | `-g comedia` |
   | romântico | `-g romance` (com comédia: `-g comedia -g romance` = qualquer um dos dois) |
   | suspense, terror, animação, documentário, ação, drama... | `-g suspense`, `-g terror`, `-g animacao`... |
   | "não muito longo", "cedo amanhã" | `--max-runtime 110` (bem curto: 95) |
   | "tem na Netflix/nos nossos streamings", "sem alugar" | `--subscribed-only` |
   | "qualquer streaming serve" | `--streaming-only` |
   | "brasileiro", "japonês" | `--country BR`, `--country JP` (ou `--language ja`) |
   | "dos anos 80", "algo recente" | `--years 1980s`, `--years 2015-` |
   | leve, para casal, para relaxar | `--prefer lighthearted,feelgood,romantic --avoid gore,rape,torture,suicide,sexual violence` |
   | "nada pesado/triste" | `--avoid` com os termos acima e mais `death of child,cancer,war crimes` |
   | "já vimos X" / "esse não" | `--exclude <tmdb_id>` (só nesta consulta) |

   - Gêneros aceitam português ou inglês. Vários `-g` significam qualquer um deles.
   - `--prefer` casa o nome exato da keyword do TMDB (em inglês). Se não souber o nome, rode `uv run recs keywords <termo>` antes.
   - `--avoid` elimina filmes cuja keyword contém o termo como palavra.
   - Em pedidos de uso imediato ("hoje", "agora"), use `--subscribed-only`, salvo se o usuário disser o contrário.
2. Leia o JSON.
   - Se houver `avisos`, corrija as flags (keyword inexistente) ou afrouxe filtros (poucos resultados) e rode de novo.
3. Apresente de 3 a 5 opções. Para cada uma, mostre:
   - título, ano, diretor e duração;
   - onde assistir (os serviços em `assinados` primeiro);
   - uma frase de motivo. Use `motivos` e `keywords_preferidas` e explique a ligação com o gosto do usuário (por exemplo: "do Scorsese, que você costuma avaliar bem"). Não invente fatos sobre o filme além do que o JSON e o conhecimento geral sustentam.
4. Para ajustes ("mais curto", "algo mais leve", "esse já vimos"), mude só a flag correspondente e rode de novo.
5. Depois que o usuário assistir, ofereça registrar o veredito com `uv run recs feedback <tmdb_id> bom|nao|ja_vi`. Só registre se ele confirmar.

## Comandos

`uv run recs ingest <zip> | match | enrich | profile | recommend | now | keywords <termo> | eval | feedback`

Testes:

```
uv run pytest -p no:cacheprovider
```
