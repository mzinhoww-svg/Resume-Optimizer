# Prompt para o Maestri (versão 2)

Crie um workspace chamado "preditor-promos-milhas" e conduza o projeto com autonomia, do início ao fim,
até entregar um sistema que **lista as próximas promoções prováveis** de pontos e milhas.

## OBJETIVO
Sistema que coleta ~36 meses de promoções (Livelo, Esfera, LATAM Pass, Smiles, Azul Fidelidade), estrutura os
eventos em PostgreSQL, treina um modelo e publica, num dashboard com alertas, uma **lista ranqueada de
promoções esperadas**, cada item com: par origem→destino, tipo de evento (bônus de transferência, compra
com desconto, acúmulo turbinado), janela provável (7, 15, 30 dias), probabilidade calibrada e faixa
esperada do bônus (P25/P50/P75). PoC: Livelo → Smiles, bônus de transferência.

## ONDE RODA (infra)
- Código: GitHub. Crie o repositório `preditor-promos-milhas` (privado) e trabalhe por branches + PR.
- Backend, Postgres, coletores, jobs e API: VPS LetsCloud via Docker Compose (Postgres, api, collectors, Caddy com HTTPS).
- Dashboard: Vercel (Next.js), lendo a API da VPS por HTTPS com chave de API. Fundo branco, painéis escuros só como acento, sem emojis.
- Segredos só em variáveis de ambiente (Vercel env, `.env` na VPS fora do git). Nunca commitar chaves.
- A nota com as chaves é a fonte. Se faltar alguma, pare e liste exatamente quais faltam.

## AGENTES (escale à vontade, feche ociosos ao fim de cada fase)
1. Orquestrador: dono do projeto, mantém TASKS.md e STATUS.md.
2. Programador (OpenCode + DeepSeek Flash): coletores, pipeline, API, testes.
3. Planejador (Claude Code + Opus 5.5): specs, revisão, validação de métricas e de vazamento temporal.
4. Frontend (Claude Code + Fable 5.1): dashboard e alertas.
Adicione agentes por coletor, de dados/QA e de testes quando acelerar a entrega.

## MÉTODO (skills Superpowers nos terminais Claude Code)
- Antes de cada fase ou decisão de arquitetura: /superpowers:brainstorming; registre opções e escolha em `docs/decisions/`.
- Fase com mais de 3 tarefas ou mais de um agente: /superpowers:writing-plans, plano em `docs/plans/`.
- Tarefas independentes: /superpowers:dispatching-parallel-agents.
- Implementação com /superpowers:test-driven-development; falhas com /superpowers:systematic-debugging;
  antes de declarar pronto, /superpowers:verification-before-completion.

## REGRAS DE DADOS
- Uma campanha pode entrar no treino com **1 fonte**. Sempre tente validar com outras fontes cuja data de
  início esteja a **±3 dias**. Registre `n_sources` e `validated` (true se ≥ 2 fontes dentro de ±3 dias);
  se as fontes divergirem, `start_at` = data mais antiga confiável, `date_conflict=true`.
- Campanha de fonte única entra com `weight` menor (ex.: 0,5; ajustável por validação) e nunca é descartada em silêncio.
- Deduplicação: chave (origem, destino, tipo) + janela de ±3 dias; mensagens repetidas viram `offer_evidence`.
- Guardar `first_seen_at` (1º alerta). **As features usam só o que era conhecido em `first_seen_at`** (sem vazamento).
- Distinguir oferta geral de segmentada (clube, público). Respeitar termos de uso e robots.txt de cada fonte.

## FASES
1. Setup: repo GitHub, Docker Compose local, schema aplicado, CI de testes.
2. **Portão de viabilidade de dados** (obrigatório): backfill de Passageiro de Primeira, Melhores Cartões,
   Pontos pra Voar e Telegram; reportar nº de campanhas por (par, tipo), % validadas e lacunas.
   Só avançar para modelagem nos (par, tipo) com ≥ 25 campanhas; os demais ficam só com baseline.
3. Estruturação: extração via OpenRouter (modelo barato, JSON estrito) + regex + dedup em `promo_campaign`.
4. Modelo (seção abaixo), PoC em Livelo → Smiles, depois global multi-par/multi-evento.
5. Produto: API, job diário que grava `prediction`, dashboard na Vercel, alertas. Deploy na VPS.

## DECISÃO DO MODELO (protocolo campeão × desafiante)
Saída: para cada (par, tipo, horizonte) → P(oferta começar em [t+1..h]) e distribuição do bônus.
Dois blocos:
- **Ocorrência**: candidatos avaliados em walk-forward (treino no passado, teste nos meses seguintes, purge de 15 dias):
  - B0 taxa-base por (par, tipo).
  - B1 **hazard empírico** em tempo discreto por (par, tipo), com ajuste sazonal por mês. Baseline e fallback.
  - C1 **LightGBM global** (hazard em formato pessoa-dia; `par`, `tipo` categóricos; features do PoC +
    ofertas recentes de pares irmãos + calendário), com calibração (isotônica ou Platt).
  - C2 Weibull/AFT (lifelines) como checagem de forma do ciclo. Não vai para produção sozinho.
- **Magnitude do bônus**: quantis empíricos condicionais (últimas N ofertas do par, por época do ano); LightGBM de quantis só se vencer em pinball loss.
- Critério: C1 vira campeão **somente** se vencer B1 em Brier e log-loss no walk-forward, com IC por bootstrap em
  blocos que exclua zero, e estiver calibrado (curva de confiabilidade). Caso contrário B1 vai para produção e o motivo é registrado.
- Retreino semanal, monitoramento de calibração e de mudança de cadência dos programas.

## CRITÉRIOS DE ACEITE
- Todo código com testes passando e CI verde.
- Planejador confirma ausência de vazamento temporal.
- Relatório do portão de viabilidade e do campeão × desafiante em `docs/`.
- Dashboard no ar na Vercel mostrando a lista de próximas promoções e as métricas do modelo em produção.

## CONTROLE
TASKS.md (tarefa, responsável, terminal, status, aceite) e STATUS.md (fase, decisões, bloqueios, próximos passos)
sempre atualizados. Fim de cada fase: resumo curto e seguir para a próxima.

## PARE E PERGUNTE APENAS PARA
- Gasto novo: criar/redimensionar servidor na LetsCloud, plano pago da Vercel, créditos de API além do já contratado.
- Credenciais que não estão na nota (login do Telegram com código SMS, chaves ausentes).
- Apagar dados coletados ou reescrever histórico do git.
- Deploy em produção (VPS e Vercel) na primeira vez, mostrando o plano antes.
