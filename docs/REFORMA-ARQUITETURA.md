# Reforma de arquitetura — 7 de outubro de 2026

Interface principal: Codex operando JSON da CLI. Pipeline determinístico:
`retrieval → eligibility/context filters → personal score → contextual rerank → availability → presentation`.

## Impacto observado antes de editar

- `score.compute` não usa disponibilidade, mas mistura elegibilidade, afinidade, penalidade de
  popularidade e boost de watchlist/salvos. Preservar fórmula e pesos; expor afinidade separada.
- `context.matching` depende da tabela de scores; `discover` só roda com contexto não vazio.
- `now` limita a 3.000 scores e corta novamente antes de consultar provedores: pode retornar
  poucos filmes mesmo havendo opções no restante do pool.
- `recommend` divide a apresentação em disponível/explorar, tornando catálogo um recorte implícito.
- `Pool.sources` já preserva múltiplas origens, mas o JSON perde essa informação.
- A skill infere assinatura de “hoje/agora”. Feedback tem apenas `bom`, `nao`, `ja_vi`.
- Não há log de interações nem perfil JSON; eval só mede recall/hits e popularidade.

## Sequência concreta de commits

1. `test: disponibilidade como metadado por padrão`: testes score/context/CLI para invariância,
   desconhecidos e filtros explícitos. Sem migração.
2. `refactor: separar seleção e disponibilidade`: eligibility.py, pipeline.py, score.py,
   context.py, availability.py, cli.py; lotes configuráveis e diagnósticos. Testar continuação,
   diversidade, pool vazio, limite e esgotamento. Tabelas derivadas recriáveis.
3. `feat: retrieval observável e explore`: candidates.py/context.py/pipeline.py, CLI e report.py;
   discover geral com perfil, fontes no JSON, explore e relatório opcional. Testar deduplicação,
   exclusões e independência de provedores. Sem migração pessoal.
4. `feat: interações e feedback explícito`: interactions.py, feedback.py, profile.py e CLI;
   tabelas locais aditivas, CSV legado lido sem reescrita, not_now apenas contextual. Testar
   persistência isolada, aliases, associação explícita de ações e ausência de aprendizado automático.
5. `feat: explicações estruturadas e avaliação`: profile.py, evaluate.py e CLI; evidências JSON,
   NDCG/MRR/diversidade, migração aditiva de eval_runs, testes com ranking conhecido.
   Atualizar AGENTS, skill, USO, ARQUITETURA, PLANO e MIGRACAO-CODEX.

## Compatibilidade e riscos

Manter comandos e flags existentes, schema_version 1 com campos aditivos e aliases de feedback.
`recommend` continua gerando Markdown, mas passa a ter lista única. `score` conserva a fórmula
legada; `score_pessoal` expõe somente afinidade. Discover geral, remoção de cortes e desempate
determinístico podem mudar a lista. Esses comportamentos exigem testes; pesos não mudam.
Limites de consulta de disponibilidade são orçamento de I/O, não pesos ou cortes de ranking geral.
Sem streaming explícito, catálogo e provedores não podem mudar IDs, scores ou ordem retornados.

Não executar ingestão, eval, consultas reais ou migrações sobre dados pessoais para validar.
Testes usam DuckDB em memória/temporário e TMDB simulado. Perfil de casal fora do escopo.

## Linha de base

75 testes passaram antes das mudanças. Git recusou status por propriedade insegura, inclusive
com safe.directory por comando; não alterar configuração global para contornar isso.

## Implementação e validação

As cinco etapas foram implementadas e verificadas com dados sintéticos. Os testes da CLI agora exercitam
filtros e score reais em DuckDB em memória, simulando apenas retrieval/rede. Há regressão para encontrar
o filme na posição 251, além do corte antigo, e para invariância do pool com assinaturas diferentes.
O ajuste `liked` implica assistido e exclui futuras recomendações; antes `bom` podia reaparecer.
O caso indefinido de IDF com um filme foi tratado com zero, sem mudar a fórmula para perfis maiores.

`--provider` substitui o filtro manual da skill e participa dos lotes progressivos. Não houve alteração
de pesos existentes. A expansão de retrieval foi testada funcionalmente, sem alegar melhora de relevância
ou comparar métricas reais; isso ainda exige eval numa cópia isolada do histórico.

Nenhuma consulta TMDB real, ingestão ou eval pessoal foi executado. Banco, export, salvos e feedback pessoais
não foram usados para validação. Commits não foram criados, pois o Git recusou acesso por propriedade.
O validador externo da skill não executou por falta de PyYAML; frontmatter e comandos foram revisados diretamente.

Validação final: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q` — **108 testes passaram**.
Também verificada a ajuda de `explore` pelo entrypoint instalado. Não há benchmark de latência novo.
