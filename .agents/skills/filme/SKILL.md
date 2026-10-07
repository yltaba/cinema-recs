---
name: filme
description: Recomenda filmes usando o perfil pessoal do cinema-recs, refina pedidos e consulta ou grava salvos e feedback pela CLI local. Use para pedidos de filmes neste projeto, não para manutenção de código ou pesquisa genérica sobre cinema.
---

# Filmes pelo Codex

Use a raiz do cinema-recs e as regras de `AGENTS.md`. O ranking é calculado pela CLI; o Codex traduz o pedido
e explica a saída. Não é necessário OpenAI API, SDK, MCP ou acesso automatizado ao Letterboxd.

## Buscar e refinar

Execute `uv run recs now ... --json`. Construa argumentos a partir do pedido e do contexto da conversa:

| Pedido | Argumentos |
|---|---|
| comédia / engraçado | `-g comedia` |
| comédia policial | `-g comedia -g crime --all-genres` |
| comédia romântica | `-g comedia -g romance --all-genres` |
| comédia OU romance | `-g comedia -g romance` |
| até duas horas | `--max-runtime 120` |
| não muito longo / cedo amanhã | `--max-runtime 110` (diga o limite adotado) |
| bem curto | `--max-runtime 95` (diga o limite adotado) |
| hoje / agora / nos meus serviços / sem alugar | `--subscribed-only`, salvo escolha diferente do usuário |
| qualquer streaming serve | `--streaming-only` |
| brasileiro / produção japonesa | `--country BR` / `--country JP` |
| em japonês | `--language ja` |
| anos 80 / de 2000 a 2010 | `--years 1980s` / `--years 2000-2010` |
| já vimos esse / esse não, nesta busca | `--exclude <tmdb_id>` |

`--subscribed-only` abrange TODOS os serviços do config. Se o usuário pedir exclusivamente Netflix, por exemplo,
filtre também a saída pelo nome exato em `streaming`; não afirme que a flag restringe a um único serviço.
Não confunda canais adicionais com a assinatura principal. Preserve esse filtro manual nos refinamentos.

Para tom leve, procure keywords com `uv run recs keywords <termo> --json`; só passe nomes exatos encontrados
em `--prefer`. Para exclusões, use `--avoid` com termos em inglês separados por vírgula. Exemplo:
`--avoid "gore,rape,torture,suicide,sexual violence"`. Texto com espaços deve ser um argumento entre aspas.
Estar em casal não implica gênero romântico ou restrição de conteúdo; use o que o pedido justifica.
As keywords não garantem ausência de um tema. Se a exclusão for importante, deixe essa limitação clara.

Mantenha na conversa os filtros aplicados e os IDs de cada opção apresentada. Em "mais curto", altere só a
duração. Em "esse já vimos", acumule a exclusão com as anteriores. Se a referência for ambígua, esclareça
qual filme antes de gravar ou excluir. Não invente continuidade de contexto entre sessões.

Para opções novas, leia os IDs de `overrides/salvos.csv` e passe-os em `--exclude`, junto às exclusões do pedido.
Não exclua os salvos quando o usuário quiser reconsiderá-los. `recs salvos --json` consulta pendentes e provedores.

Leia `avisos`. Corrija argumento inválido ou preferência sem correspondência no máximo uma vez por pedido,
quando houver uma correção sustentada pelos dados. Se ainda faltarem opções, apresente as existentes e explique
o limite. Não transforme poucos resultados em uma sequência de buscas nem relaxe restrições obrigatórias.
Proponha uma alteração concreta de filtro para o usuário escolher quando necessário.

## Apresentar

Apresente de 3 a 5 opções, se existirem, respeitando a ordem retornada entre as que atendem ao pedido.
Mostre título, ano, diretor, duração, serviços (assinados primeiro) e uma frase baseada em `motivos` e
`keywords_preferidas`. Campo ausente significa informação indisponível. Score não é probabilidade de gostar.
Não invente sinopse, nota pessoal ou disponibilidade. A disponibilidade é do cache TMDB/JustWatch e pode mudar.
Não use relatórios antigos como prova de onde assistir hoje. Termine com `atribuicao` da saída.

## Salvar e dar feedback

- "Salve essas": execute `uv run recs salvar <ids apresentados...> --contexto "<resumo>" --json`.
  Salve somente as opções referidas; confira a saída. O comando evita duplicatas.
- "O que temos salvo?": `uv run recs salvos --json`; apresente os pendentes com os provedores retornados.
- "Assisti X e gostei": ofereça registrar `bom`. Se já disser "registre que gostei de X", execute diretamente
  `uv run recs feedback <id> bom --json`, sem pedir novamente.
- `bom` entra com peso positivo; `ja_vi` exclui como assistido; `nao` exclui das recomendações e não aprende
  afinidade negativa. "Não quero agora" deve ser exclusão da consulta, não feedback permanente.
- O último veredito prevalece. Só anuncie gravação bem-sucedida após sucesso do comando.

## Falhas e primeiro uso

Se faltarem dados, explique a preparação `ingest → match → enrich` descrita no README e peça o caminho do export
se não tiver sido fornecido. Não substitua a consulta pessoal por títulos inventados. Se a chave estiver ausente,
oriente configurar `TMDB_API_KEY` sem pedir seu valor na conversa. Em falha da API, informe o erro sanitizado;
não exponha traceback com dados sensíveis nem prometa resultados. Não execute eval para fazer recomendações.

## Exemplos de comando

```powershell
uv run recs now -g comedia -g romance --all-genres --max-runtime 120 --subscribed-only --json
uv run recs now -g comedia -g romance --all-genres --max-runtime 90 --subscribed-only --json
uv run recs now -g terror --years 1970s --streaming-only --json
```

A segunda linha é o refinamento "até 90 minutos" da primeira. Esses são exemplos, não consultas executadas.
