---
name: filme
description: Recomenda filmes usando o perfil pessoal do cinema-recs, refina pedidos e grava feedback pela CLI local. Use para pedidos de filmes neste projeto, não para manutenção de código ou pesquisa genérica sobre cinema.
---

# Filmes pelo Claude Code

Use a raiz do cinema-recs e as regras de `CLAUDE.md`. O ranking é calculado pela CLI; o agente traduz o pedido
e explica a saída. Não é necessário API de LLM, SDK, MCP ou acesso automatizado ao Letterboxd.

## Buscar e refinar

Use `uv run recs explore ... --json --n 5` para descoberta ampla ("me recomende um filme",
"cinema japonês", "me surpreenda") e `uv run recs now ... --json --n 5` para pedidos do momento.
Ambos usam o mesmo pipeline; o relatório só é criado com `--markdown <caminho>`.
Construa argumentos a partir do pedido e do contexto da conversa:

| Pedido | Argumentos |
|---|---|
| comédia / engraçado | `-g comedia` |
| comédia policial | `-g comedia -g crime --all-genres` |
| comédia romântica | `-g comedia -g romance --all-genres` |
| comédia OU romance | `-g comedia -g romance` |
| até duas horas | `--max-runtime 120` |
| não muito longo / cedo amanhã | `--max-runtime 110` (diga o limite adotado) |
| bem curto | `--max-runtime 95` (diga o limite adotado) |
| hoje / agora | sem restrição de disponibilidade implícita |
| nos meus serviços / só nas minhas assinaturas / sem alugar (no contexto de streaming) | `--subscribed-only` |
| qualquer streaming serve | `--streaming-only` |
| só na Netflix | `--provider Netflix` |
| brasileiro / produção japonesa | `--country BR` / `--country JP` |
| em japonês | `--language ja` |
| anos 80 / de 2000 a 2010 | `--years 1980s` / `--years 2000-2010` |
| já vimos esse / esse não, nesta busca | `--exclude <tmdb_id>` |

`--subscribed-only` abrange TODOS os serviços do config. `--provider Netflix` restringe a esse serviço no
Python, incluindo a busca progressiva. Não confunda canais adicionais com a assinatura principal.
Preserve serviços específicos nos refinamentos; não filtre nem reordene manualmente a saída.

Para tom leve, procure keywords com `uv run recs keywords <termo> --json`; só passe nomes exatos encontrados
em `--prefer`. Para exclusões, use `--avoid` com termos em inglês separados por vírgula. Exemplo:
`--avoid "gore,rape,torture,suicide,sexual violence"`. Texto com espaços deve ser um argumento entre aspas.
Estar em casal não implica gênero romântico ou restrição de conteúdo; use o que o pedido justifica.
Disponibilidade não representa gosto. Nunca adicione restrição de streaming só pela urgência ou por estar
em casal. "De preferência nos meus serviços" é preferência suave: informe os serviços da saída e deixe
claro que não aplicou um filtro obrigatório. A CLI ainda não tem rerank suave por streaming; não converta
essa preferência em `--subscribed-only` nem reordene por conta própria.
As keywords não garantem ausência de um tema. Se a exclusão for importante, deixe essa limitação clara.

### Pedidos temáticos e origem

- Só use `--country`, `--language` e `-g` quando o pedido ou a conversa os justificarem. Um tema ("algo que me
  inspire", "para descansar", "sobre trabalho") não é um país, idioma ou gênero: traduza-o em `--prefer`
  (keywords exatas de `recs keywords`) e `--avoid`, numa busca ampla com `explore`. Não faça uma segunda busca
  recortada por origem só porque o perfil tem afinidade com ela.
- Pedidos por prompt têm escopo amplo: `--prefer` pesa pouco, então a CLI é uma das fontes. Complete com
  conhecimento geral de cinema para cobrir o tema e deixe claro que a disponibilidade desses títulos não foi
  verificada pelo programa.
- Sem origem pedida, a CLI já equilibra a seleção: se um país passa de `score.max_country_share` (40%), ela
  acrescenta filmes de outros lugares com `complemento_origem: true` (ver `diagnostico.availability.origem`).
  A lista pode crescer até 2n; apresente os complementos como "de outros lugares".
- Confira a lista final antes de apresentar: sem origem pedida, nenhum país deve passar de ~40% dos títulos,
  incluindo os de conhecimento geral. Se passar, troque os excedentes por títulos de outras origens.

Mantenha na conversa os filtros aplicados e os IDs de cada opção apresentada. Em "mais curto", altere só a
duração. Em "esse já vimos", acumule a exclusão com as anteriores. Se a referência for ambígua, esclareça
qual filme antes de gravar ou excluir. Não invente continuidade de contexto entre sessões.

Leia `avisos` e `diagnostico`: disponibilidade obrigatória é verificada em lotes; `stop_reason=limit`
significa candidatos ainda não verificados, e `exhausted` significa pool esgotado. Não confunda ambos.
Corrija argumento inválido ou preferência sem correspondência no máximo uma vez por pedido,
quando houver uma correção sustentada pelos dados. Se ainda faltarem opções, apresente as existentes e explique
o limite. Não transforme poucos resultados em uma sequência de buscas nem relaxe restrições obrigatórias.
Proponha uma alteração concreta de filtro para o usuário escolher quando necessário.

## Apresentar

Apresente de 3 a 5 opções principais, se existirem, respeitando a ordem retornada entre as que atendem ao pedido,
mais os complementos de origem que a CLI acrescentar.
Guarde o `interaction_id` junto dos IDs apresentados. O registro automático contém as opções emitidas
pela CLI, com ranks, scores e fontes; peça `--n` compatível com a quantidade que vai apresentar.
Inclua as opções com `complemento_origem: true` quando houver, num bloco "de outros lugares".
Mostre título, ano, diretor, duração, serviços conhecidos (assinados primeiro) e uma frase baseada em `motivos` e
`keywords_preferidas`. Campo ausente significa informação indisponível. Score não é probabilidade de gostar.
Não invente sinopse, nota pessoal ou disponibilidade. A disponibilidade é do cache TMDB/JustWatch e pode mudar.
Não use relatórios antigos como prova de onde assistir hoje. Termine com `atribuicao` da saída.
`disponibilidade_conhecida=false` não prova ausência do filme em todos os serviços. `score_pessoal` é
afinidade; `score` mantém ajustes legados de popularidade/watchlist; `score_contexto` incorpora
keywords preferidas. Nenhum deles inclui provedores. Use `fontes` para explicar como o filme entrou no pool.

Para perguntas sobre gosto, consulte `uv run recs profile --json`; use `features`, `evidencias` e `resumo`.
Não trate pouca evidência como preferência consolidada. Não execute uma nova busca de filmes só para explicar o perfil.

## Salvar e dar feedback

- Não há lista de salvos local. A watchlist do Letterboxd é a única lista "para ver": se o usuário pedir para
  salvar, explique que isso é feito lá e que entra aqui no próximo export manual. Não grave nada local.
- "Assisti X e gostei": ofereça registrar `liked`. Se já disser "registre que gostei de X", execute diretamente
  `uv run recs feedback <id> liked --json`, acrescentando `--interaction <id>` quando a associação for conhecida.
- `liked` entra com peso positivo e indica assistido; `disliked` registra que não gostou, sem aprender peso
  negativo ainda; `already_seen` registra visto sem avaliação; `not_interested` exclui sem avaliar gosto.
  `bom`, `nao` e `ja_vi` continuam aliases. Não confunda "não gostei" com "não tenho interesse".
- "Não quero agora" exclui só da consulta via `--exclude`. Se pedir registro contextual explícito, use
  `feedback <filme> not_now --interaction <id> --json` e acumule o `exclude` retornado no próximo refinamento.
  Isso não altera o CSV permanente nem exclui o filme em futuras consultas independentes.
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
