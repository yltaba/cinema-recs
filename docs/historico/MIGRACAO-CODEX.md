# Migração para Codex

> **Arquivado em 07/10/2026.** O projeto voltou a usar só o Claude Code; `AGENTS.md` e `.agents/` foram
> removidos. Estado atual: [CLAUDE-CODE.md](../CLAUDE-CODE.md). Este arquivo é registro histórico.

## Atualização arquitetural — 7 de outubro de 2026

A reforma está descrita em [ARQUITETURA.md](../ARQUITETURA.md), com plano de commits e impacto em
[REFORMA-ARQUITETURA.md](../REFORMA-ARQUITETURA.md). As seções seguintes registram a migração original de 6/10;
as mudanças abaixo prevalecem sobre seus contratos e pendências históricos.

- `now` e `explore` compartilham o pipeline; streaming só filtra por pedido explícito. A skill não
  traduz “hoje/agora” em assinatura. `recommend` mantém o comando e arquivo, com lista única.
- JSON v1 recebe campos aditivos: `interaction_id`, `consulta`, `diagnostico`; por filme,
  `score_pessoal`, `fontes`, `ajustes`, `motivos_detalhados`, `disponibilidade_conhecida`.
- `diagnostico` traz retrieved/enriched/eligible/context_matched/ranked/returned, fontes, contagens
  cumulativas exclude/genres/runtime/language/country/years/avoid, e availability com checked/matched/
  batches/returned/stop_reason. `limit` não significa esgotamento do pool.
- `profile --json` expõe afinidades e evidências. `interaction <id> --json` consulta o registro local.
- `salvar` e `feedback` recebem `--interaction`; feedback adiciona `veredito_canonico` e aceita
  liked/disliked/not_interested/already_seen/not_now, preservando aliases. `not_now` não é persistente no CSV.
- Migrações são aditivas e executadas no uso: tabelas de interações criadas se ausentes e colunas
  NDCG/MRR/diversidade adicionadas a eval_runs. CSV antigo é normalizado na leitura, sem reescrita.
- O log mede opções emitidas pela CLI; não mede se o usuário assistiu ou leu a apresentação do Codex.
  Nenhum aprendizado automático usa o log. Ações só são ligadas à consulta quando seu ID é informado.
- Perfil de casal permanece fora do escopo. O eval ainda requer cópia isolada dos dados e pode acessar rede.

## Registro histórico de 6/10

Implementada em 6 de outubro de 2026, a pedido do usuário após o cancelamento do Claude Code.
O Codex é a interface conversacional do projeto. O ranking, a configuração e os dados pessoais continuam
no pipeline Python existente. Não foram introduzidos OpenAI API, SDK de agentes, MCP ou serviços novos.

## Instruções e entrada

- `AGENTS.md` (removido): regras permanentes, ambiente, testes e encaminhamento para o roteiro.
- Skill filme (hoje em `.claude/skills/filme/`): interpretação, refinamentos, apresentação, salvos e feedback.
- [USO.md](../../USO.md): guia de uso; [README](../../README.md): instalação e preparação dos dados.

A organização segue a documentação oficial de [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
e de [skills locais](https://learn.chatgpt.com/docs/build-skills). A skill está em `.agents/skills/filme/`,
com seleção automática permitida e invocação explícita por `$filme`. Abra uma nova sessão no projeto para
carregar as instruções; se a skill não aparecer, reinicie o Codex. Não foram alteradas configurações globais.

O antigo `CLAUDE.md` foi removido. As referências restantes ao Claude documentam a decisão de migração ou
a avaliação histórica, sem orientar o uso atual. O piloto comparativo com Claude não é requisito para adoção
e não foi realizado; não se afirma superioridade de um modelo sobre outro.

## Comportamento entregue

Pedidos em português são traduzidos em `recs now --json`. O roteiro distingue comédia policial de comédia
romântica, combina gêneros com `--all-genres` quando apropriado e preserva restrições nos refinamentos.
Poucos resultados não autorizam relaxamento automático. Keywords de preferência precisam existir no cache;
exclusões de conteúdo não são garantia de ausência do tema.

O Codex apresenta os motivos e provedores da saída, identifica os filmes pelos IDs e pode salvar as opções
solicitadas. Um pedido explícito de registro já autoriza feedback; um comentário permite oferecer o registro.
"Não quero agora" exclui apenas da busca, sem criar feedback permanente. Salvos e feedback persistem em CSV;
os filtros e referências como "o segundo" pertencem à conversa, não a uma memória persistente implementada.

Erros HTTP 4xx do TMDB, exceto o tratamento específico de 404, agora geram `TMDBError` sem URL ou corpo da resposta.
A CLI não exibe variáveis locais nos tracebacks. Testes usam chaves fictícias para verificar a sanitização.
Isso corrige o caminho demonstrado na avaliação; não representa uma auditoria de todos os possíveis logs externos.

## Contrato JSON de sucesso

Todos estes comandos aceitam `--json` e retornam `schema_version: 1`. Os campos anteriores de `now` foram mantidos.

| Comando | Campos principais além da versão |
|---|---|
| `now` | `contexto` (texto), `filmes`, `avisos`, `atribuicao` |
| `keywords <termo>` | `keywords`: itens com `nome` e `filmes` (contagem no cache) |
| `salvar <ids...>` | `salvos` (IDs novos), `ja_salvos` (IDs já existentes) |
| `salvos` | `filmes` pendentes, `total_salvos`, `atribuicao` |
| `feedback <id> <veredito>` | `tmdb_id`, `veredito`, `efeito` |

Em `now`, cada filme traz ID, títulos, ano, diretor, duração, gêneros, scores, motivos, keywords preferidas,
indicadores de watchlist/salvo, assinados, streaming e indicador de aluguel/compra. Em `salvos`, cada filme traz
ID, título, ano, duração, contexto salvo e os mesmos campos de disponibilidade.
Listas vazias são resultados válidos. Erros ainda usam código de saída não zero e stderr; não há schema de erros.
Os modos de tabela existentes continuam disponíveis sem `--json`.

## Verificação realizada

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q
```

Resultado: **75 testes passaram**. Os novos testes cobrem JSON da CLI, duplicação de salvos, feedback e remoção
dos pendentes, consulta de keywords, resultados vazios, argumentos de contexto e falhas HTTP sem credenciais.
O teste de `now` usa etapas simuladas; os testes existentes de contexto exercitam filtros SQL com dados sintéticos.
As ajudas de `now` e `salvos` também foram executadas pelo entrypoint instalado.

O validador `quick_validate.py` da skill foi tentado, mas o ambiente não possui PyYAML. O frontmatter simples,
nome, descrição, referências e exemplos foram revisados diretamente, sem adicionar dependência ao projeto.
A descoberta automática em uma nova sessão e a qualidade conversacional em uso real não foram medidas por esses testes.

Não foram executadas consultas reais ao TMDB, ingestão ou eval sobre o banco pessoal; não foram alterados
export, banco, salvos, feedback ou pesos. O Git recusou a leitura de status por propriedade insegura, mesmo
com exceção por comando; nenhuma configuração global foi alterada e nenhum commit foi criado.

## Melhorias que continuam pendentes

A [avaliação anterior](AVALIACAO-MELHORIAS-MIGRACAO-CODEX.md) fica como registro histórico e backlog.
A migração da interface não implementa todas as sugestões desse documento:

- Semântica dos multiplicadores com scores negativos; perfil mínimo e holdout vazio.
- Isolamento e reprodutibilidade do eval; ingestão por snapshot e transação.
- Busca de disponibilidade em lotes além do corte atual de candidatos.
- Contexto JSON estruturado, schema de erros, validação ampla de entradas e diagnóstico de primeiro uso.
- Tratamento mais abrangente de retries/HTTP, CI e evolução de diversidade.
- Perfil de casal, desfazer/editar salvos e aprendizado de afinidade negativa pelo feedback.

O eval pode acessar a rede e deixa tabelas derivadas no último seed. Deve ser usado numa cópia isolada para
comparar alterações de ranking. O cache de provedores continua seguindo o TTL configurado; disponibilidade
não é uma verificação em tempo real no aplicativo do serviço de streaming.
