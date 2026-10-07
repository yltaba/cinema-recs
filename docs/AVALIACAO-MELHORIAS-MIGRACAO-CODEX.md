# Melhorias do cinema-recs e avaliação da migração para Codex

Data: 6 de outubro de 2026.

> Registro histórico da avaliação anterior à implementação. O usuário decidiu adotar Codex após cancelar
> Claude Code. A proposta de piloto comparativo e manutenção de `CLAUDE.md` abaixo foi superada por essa decisão.
> Estado atual, correções entregues e pendências: [MIGRACAO-CODEX.md](MIGRACAO-CODEX.md).
> As constatações abaixo descrevem o código examinado naquela avaliação, não uma nova auditoria pós-migração.

## Parecer

**Vale fazer um piloto de migração para Codex. A adaptação técnica parece pequena, mas ainda não há evidência de superioridade sobre Claude Code neste projeto.** O núcleo é uma CLI Python determinística, com DuckDB e TMDB; não identifiquei SDK nem chamadas a modelos Anthropic no código examinado. A dependência do Claude está principalmente no roteiro de interpretação de pedidos em `CLAUDE.md` e em referências na documentação.

A migração pode preservar o algoritmo, o banco e os comandos existentes. Seu resultado deve ser medido em duas frentes: qualidade da interface conversacional para escolher filmes e qualidade do trabalho de desenvolvimento. Trocar o agente, por si só, não corrige problemas do recomendador.

Minha ordem sugerida é: corrigir falhas concretas, tornar a avaliação reproduzível, adaptar as instruções e comparar os agentes com as mesmas tarefas e dados. Não recomendo reintroduzir reranking por LLM, descartado no `PLANO.md`, apenas para justificar a migração.

## Escopo e evidências

Foram examinados a documentação principal, `CLAUDE.md`, configuração, dependências, módulos do pipeline e testes. A suíte foi executada com o Python do ambiente existente:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q
```

Resultado: **68 testes passaram em 7,00 segundos**. Verificações adicionais utilizaram bancos em memória e HTTP simulado, sem ler a chave real do `.env` nem consultar o TMDB. Não executei uma avaliação sobre o banco pessoal nem uma comparação real com Claude Code. Não alterei código, pesos, dados ou instruções de agentes; este documento é a entrega da análise.

O Git recusou a consulta de status por propriedade considerada insegura, inclusive na tentativa de exceção limitada ao comando. Não alterei a configuração global para contornar isso; portanto, não afirmo que a árvore Git esteja limpa. A pasta `.pytest_cache` também apresentou restrição de acesso; desabilitar esse cache permitiu executar os testes.

## O que preservar

- Separação entre interpretação do pedido e ranking determinístico, que facilita trocar o agente.
- Módulos por etapa, JSON bruto em cache e tabelas derivadas reconstruíveis.
- Matching com revisão e overrides, explicações por contribuição e diversidade por diretor.
- Regra de avaliar mudanças de pesos e limites antes de adotá-las.
- Entrada por export do Letterboxd e atribuição das fontes nas recomendações.
- `uv.lock` e testes sem dependência de uma API real.

## Melhorias prioritárias

Prioridades: **P0** = corrigir primeiro; **P1** = próxima rodada de confiabilidade; **P2** = evolução. Esforço relativo: pequeno, médio ou grande, sem estimativa de prazo contratual.

| Prioridade | Sugestão | Evidência local | Esforço |
|---|---|---|---|
| P0 | Remover credenciais das mensagens de erro | `src/recs/tmdb.py`, `TMDB.fetch` | Pequeno |
| P0 | Corrigir instruções de gênero e relaxamento de filtros | `CLAUDE.md`, tabela e passo 2 | Pequeno |
| P1 | Definir semântica dos multiplicadores para scores negativos | `src/recs/score.py`, `compute` | Médio |
| P1 | Tratar perfil mínimo e holdout vazio | `profile.build`, `evaluate.holdout_ids` | Pequeno |
| P1 | Tornar o eval isolado e reproduzível | `evaluate.run_seed`, `previous`, `cli.eval_` | Médio |
| P1 | Fazer ingestão por snapshot e transação | `ingest.unpack`, `load` | Médio |
| P1 | Versionar o contrato JSON e testar a CLI | `cli.now`, conjunto `tests/` | Médio |
| P1 | Ampliar a busca quando o corte anterior à disponibilidade esvazia a lista | `cli.now`, linhas 306–320 | Médio |
| P2 | Melhorar diagnóstico, validação e recuperação da API | `config.py`, `tmdb.py`, `cli.py` | Médio |
| P2 | Evoluir feedback, diversidade e perfil de casal | `profile.py`, `saved.py`, `PLANO.md` | Médio/grande |

### 1. Credencial pode aparecer numa exceção HTTP

**Confirmado com chave fictícia.** O cliente envia a chave v3 na query string; `raise_for_status()` produz uma exceção cuja mensagem inclui a URL. Um HTTP 401 simulado incluiu `SYNTHETIC_TEST_KEY` no texto da exceção. Não é evidência de vazamento real ocorrido, mas é um caminho concreto que viola a regra de nunca imprimir a chave.

Sugestão: converter falhas HTTP em erros de domínio contendo status, endpoint sem query sensível e orientação de recuperação. Revisar também traceback/logs de depuração. Testar 401/403 e verificar que a chave fictícia não aparece em stdout, stderr ou logs.

### 2. Corrigir o contrato conversacional antes de copiá-lo

**Constatação no arquivo.** A linha de gênero composto inclui “comédia policial” e “comédia romântica”, mas fornece o mesmo comando com `-g crime`. Separar os exemplos: romance deve usar `-g comedia -g romance --all-genres`.

O passo 2 manda afrouxar filtros quando há poucos resultados. Isso pode apagar uma restrição explícita, como “sem alugar”, duração máxima ou exclusão de conteúdo. Diferenciar restrições obrigatórias de preferências; quando não houver resultado, preservar as obrigatórias e apresentar uma alternativa de relaxamento para escolha do usuário. Limitar tentativas para evitar buscas repetidas sem critério.

As keywords disponíveis não garantem ausência de um tema: explicitar essa limitação quando ela afetar uma exclusão importante. O agente deve fundamentar títulos, duração, disponibilidade e motivos nos dados retornados.

### 3. Multiplicadores mudam de sentido quando a base é negativa

**Confirmado em banco sintético usando `score.compute`.** Com a mesma afinidade negativa:

| Caso | Score observado |
|---|---:|
| 100 votos, sem boost | -1,773 |
| 100 votos, watchlist | -2,305 |
| 10.000 votos, sem boost | -1,260 |

O boost da watchlist piora a posição relativa; a penalidade de popularidade melhora a posição do filme mais popular. `context.rerank` já protege o bônus de contexto para scores positivos, mas `score.compute` aplica os multiplicadores a toda a base.

Sugestão: decidir explicitamente o comportamento desejado para bases negativas e zero. Comparar, por exemplo, aplicação de boost apenas à parte positiva e penalidade aditiva calibrada. Exigir testes de monotonicidade e eval comparativo antes de escolher uma fórmula; não alterar pesos apenas por intuição.

### 4. Perfil mínimo e avaliação sem histórico suficiente

**Confirmado.** Com um filme no perfil, a expressão de IDF `ln(N / count(*)) / ln(N)` produziu `NaN`. Sem filmes elegíveis, `holdout_ids` tentou amostrar um elemento de uma lista vazia e levantou `ValueError`.

Sugestão: definir IDF para `N <= 1`, recusar ou sinalizar avaliação insuficiente, validar `0 < holdout < 1` e manter conjunto de treinamento útil. Testar zero/um filme, nenhuma nota alta e intervalos inválidos. Afinidades e scores publicados devem ser finitos.

### 5. O eval atual não basta para comparar mudanças nem agentes

**Constatações no código:**

- `run_seed` pode buscar filmografias e metadados na rede. “Offline” descreve o método de avaliação, mas a execução não é necessariamente desconectada ou congelada.
- Perfil, candidatos e scores ficam no estado do último seed; a própria CLI avisa para reconstruí-los.
- `previous` seleciona por fração e rótulo, sem exigir o mesmo histórico, universo de candidatos ou conjunto de seeds.
- O eval não passa `seeds_dir` ao gerador; salvos e listas curadas usados na recomendação normal ficam de fora. Feedback também é excluído deliberadamente.
- `hit20`/`hit50` dividem pelo tamanho do holdout: são medidas de recall em K, e não uma taxa binária de acerto por consulta.

Sugestão: criar execução sobre snapshot/cópia isolada, fixar dados e relógio quando necessário, registrar versão do código, hash do histórico e configuração, seeds e IDs escondidos. Oferecer modo estritamente sem rede, que informe cache insuficiente. Manter a avaliação de histórico como tal e acrescentar cenários para contexto, salvos e disponibilidade.

Renomear ou documentar as métricas com precisão. Acrescentar baselines simples e medidas sensíveis à posição, como NDCG, além de diversidade e atendimento às restrições. Uma divisão temporal pode complementar o holdout aleatório quando houver datas confiáveis. Esses resultados avaliam o recomendador; a tradução de linguagem natural exige avaliação própria.

### 6. Evitar mistura de exports e carga parcial

**Constatação no código.** `unpack` extrai/copia sobre `data/raw` existente. Um CSV que desapareceu do novo export pode permanecer do anterior. `load` apaga `lb_films` antes da inserção, sem transação explícita envolvendo as duas operações.

Sugestão: preparar cada export em diretório de staging novo, validar arquivos/colunas, carregar em transação e só então promover o snapshot. Preservar a importação anterior em caso de falha. Testar dois exports consecutivos, remoção de arquivo opcional, CSV inválido e importação vazia. Registrar origem, data e hash do export.

### 7. Fazer da CLI uma interface estável para qualquer agente

`now --json` é uma boa base, mas não há testes de integração de CLI no conjunto examinado. Acrescentar `schema_version`, contexto estruturado efetivamente aplicado, códigos de aviso, data da consulta de disponibilidade e erros legíveis por máquina. Padronizar JSON nos comandos que o agente usa para keywords, salvos e feedback; manter mensagens de progresso fora de stdout no modo JSON.

Adicionar testes com `CliRunner`, banco temporário e HTTP simulado: primeiro uso sem tabelas, filtros inválidos, API indisponível, lista vazia, atribuição, exclusões e gravação de feedback. Validar que nenhuma pontuação não finita atravesse a serialização.

### 8. Não confundir corte de busca com falta de filmes disponíveis

**Constatação no código; impacto real ainda não medido.** `now` limita os candidatos antes de consultar provedores e filtrar pelos serviços assinados. Pode retornar poucos filmes mesmo que candidatos abaixo do corte estejam disponíveis.

Sugestão: consultar disponibilidade em lotes sucessivos até preencher a lista, esgotar candidatos ou atingir um orçamento explícito. Informar quando a busca foi limitada pelo orçamento. Testar um cenário em que os primeiros candidatos não estejam nos serviços assinados e candidatos posteriores estejam.

### 9. Melhorias operacionais e de produto

- **Configuração validada:** rejeitar duração negativa, intervalos invertidos, `n` não positivo e valores incompatíveis. Unificar a política de `.env`: `CLAUDE.md` exige arquivo no projeto, enquanto README e `find_dotenv` permitem diretórios ancestrais.
- **Diagnóstico:** um `recs doctor` pode verificar tabelas necessárias, versão do schema, configuração, disponibilidade de credencial sem exibi-la e idade do cache.
- **HTTP:** testar timeout, 429, 5xx e `Retry-After`. Hoje esse header é convertido diretamente para `float`; robustecer parsing e limites de espera. Contabilizar tentativas/falhas além de respostas bem-sucedidas.
- **Reprodutibilidade:** desempatar ranking com `tmdb_id`; criar CI com instalação a partir do lockfile e testes sem rede. Acrescentar lint gradualmente, sem transformar uma migração pequena em reescrita.
- **Dados pessoais:** decidir conscientemente se feedback, salvos e relatórios devem ser versionados; `.gitignore` cobre `.env` e `data/`, mas não esses arquivos. Usar fixtures sintéticas para compartilhar avaliações.
- **Feedback:** distinguir “não gostei” de “não quero agora”; o atual `nao` exclui, mas não ensina uma afinidade negativa. Implementar desfazer e edição de salvos antes de ampliar automações.
- **Perfil de casal:** é uma evolução já prevista. Usar históricos separados e comparar média, mínimo e restrição de veto; não assumir que a fórmula mínimo é a melhor sem validação com os dois usuários.

## Migração proposta

### Estrutura mínima

Criar `AGENTS.md` com as regras permanentes: arquitetura, comandos de instalação/testes, entrada via export, tratamento de segredos, atribuição e exigência de eval comparativo. O Codex descobre esse arquivo na hierarquia do projeto; `CLAUDE.md` não deve ser presumido como carregado automaticamente. Há suporte a nomes alternativos configurados, mas um arquivo explícito facilita a portabilidade. [Documentação oficial de AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

Mover o roteiro extenso de recomendação para `.agents/skills/filme/SKILL.md`, com gatilho restrito a pedidos de filmes e refinamentos. Incluir os exemplos corrigidos, preservação de filtros, interpretação do JSON e regra de feedback. O Codex oferece descoberta de skills nessa pasta do repositório. [Documentação oficial de skills](https://learn.chatgpt.com/docs/build-skills).

Manter `CLAUDE.md` durante o piloto, apontando explicitamente para as mesmas regras e roteiro, e verificar que ambos os agentes os leem. Evitar duas cópias extensas que possam divergir. Atualizar README, USO, PLANO e textos de ajuda para descrever o fluxo independente do agente.

Não há necessidade demonstrada de introduzir OpenAI API, Agents SDK, MCP ou novos serviços para esta migração. O Codex pode operar a CLI já existente. Configurações globais, hooks e integrações pessoais do Claude Code não foram auditados; se existirem fora do repositório, precisam de inventário separado.

### Piloto comparável

Usar a mesma versão do código, snapshot de dados, instruções equivalentes e condições de cache. Registrar versão/modelo de cada agente, permissões e ferramentas disponíveis. Executar sequencialmente ou com bancos isolados para não misturar gravações no DuckDB.

Montar pelo menos 20 cenários conversacionais e três tarefas de desenvolvimento. Repetir os casos para observar variação; essa amostra inicial orienta a decisão, sem pretensão de demonstrar superioridade estatística.

| Cenário | Critério de sucesso |
|---|---|
| “Comédia romântica para hoje, sem alugar” | Romance + comédia em interseção; apenas assinados |
| “Agora mais curto” | Altera duração e preserva as restrições anteriores |
| “Esse já vimos” | Exclui o ID correto da consulta |
| “Nada de violência sexual” | Mantém exclusão e não promete cobertura inexistente |
| Poucos resultados ou keyword inexistente | Diagnostica a causa sem apagar restrições explícitas |
| “Salve essas” e duplicação do pedido | Salva IDs corretos sem duplicar registros |
| Comentário sobre um filme assistido | Respeita a regra de confirmação de feedback |
| API simulada indisponível | Explica a falha sem inventar resultados nem expor credencial |
| Corrigir perfil com um filme | Entrega correção pequena e teste de regressão pertinente |
| Corrigir contrato JSON | Mantém compatibilidade ou documenta a alteração |
| Propor ajuste de ranking | Executa comparação válida antes de alterar configuração |

Medir: atendimento às restrições, correspondência entre pedido e flags, afirmações sustentadas pelo JSON, intervenções humanas, tentativas, latência, custo/uso disponível e qualidade do diff. Para manutenção, revisar correção, escopo e testes; número de linhas geradas não é medida de qualidade.

**Critério sugerido para adoção:** nenhuma violação crítica das regras nos cenários executados; pelo menos 95% dos casos com filtros corretos; qualidade de manutenção equivalente ou melhor na revisão; redução observável de tempo/intervenções ou vantagem de custo. Os limiares são uma proposta para o piloto, não resultados já obtidos. Ausência de falhas na amostra não garante ausência em uso futuro.

### Sequência e reversibilidade

1. Corrigir instruções, sanitização de erros e casos mínimos com regressões.
2. Congelar uma baseline e isolar avaliação/dados de teste.
3. Adicionar `AGENTS.md` e skill, mantendo compatibilidade com Claude Code.
4. Executar os mesmos cenários nos dois agentes e revisar resultados.
5. Adotar Codex se os critérios forem atendidos; manter Claude Code se houver vantagem clara ou regressões relevantes.

O rollback é simples se a migração inicial se limitar à camada de instruções: voltar ao agente anterior preservando CLI, schema e dados. Alterações do algoritmo devem ser avaliadas separadamente para que seus efeitos não sejam atribuídos indevidamente à troca de agente.
