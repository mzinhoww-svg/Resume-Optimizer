# Preditor de promoções de milhas/pontos (Livelo, Esfera → LATAM Pass, Smiles, Azul)

> Nota de método: esta especificação foi escrita **sem navegação web ao vivo**. Nomes de
> repositórios, modelos HF e modelos do OpenRouter vêm de conhecimento prévio e **precisam ser
> verificados** (existência, licença, manutenção, preço atual) antes de adotar. Os termos de uso
> e o `robots.txt` de cada fonte também precisam ser conferidos antes de qualquer coleta.

## 1. Projetos e modelos base

**Análise de sobrevivência / eventos recorrentes**
- `lifelines` (Cox PH, Weibull AFT, Kaplan-Meier; modelo de eventos recorrentes via formato start/stop).
- `scikit-survival` (Random Survival Forest, Gradient Boosting Survival), `pycox`/`DeepSurv` (só se houver muito dado).
- Para hazard em tempo discreto: qualquer classificador com formato "pessoa-dia" (é o que o PoC faz).

**Previsão de séries/eventos**
- `LightGBM`/`XGBoost` + `sktime`/`tsfresh`/`mlforecast` para lags e janelas.
- `statsforecast` (baselines Croston/TSB para demanda intermitente — adequados a eventos esparsos).
- Modelos fundacionais de séries temporais no Hugging Face (família Chronos da Amazon, TimesFM do Google,
  Lag-Llama, Moirai): úteis como baseline *zero-shot*, mas **pouco promissores aqui**: a série é
  de eventos raros, não uma curva contínua.
- `Prophet`/`NeuralProphet` só para sazonalidade agregada (contagem semanal de ofertas do ecossistema).

**NLP (extração dos alertas, texto em PT-BR)**
- Encoders: `neuralmind/bert-base-portuguese-cased` (BERTimbau) ou `xlm-roberta-base` para classificar
  "é promoção de transferência?" e fazer NER (percentual, datas, programa).
- Zero/few-shot com LLM costuma bastar: o volume é pequeno (centenas de mensagens/mês) e o formato é estável.
- Dedup de alertas repetidos: `sentence-transformers` multilíngue (`paraphrase-multilingual-MiniLM`) + similaridade.

**LLMs via OpenRouter (apenas extração/estruturação, não previsão)**
Os nomes do enunciado (3.5 Sonnet, Llama 3.1 70B) já podem estar defasados; consulte `openrouter.ai/models`.
Critério: JSON estruturado confiável + preço/Mtok baixo + PT-BR.

| Camada | Uso | Classe de modelo sugerida |
|---|---|---|
| Triagem em massa | classificar relevante/irrelevante | modelos "flash/mini/haiku" ou DeepSeek (barato) |
| Extração estruturada | texto → JSON do esquema abaixo | classe Haiku / Gemini Flash / DeepSeek V3-like; `response_format=json_object` |
| Casos ambíguos | regras com condições (clube, CPF, faixas) | classe Sonnet apenas para a fila de baixa confiança |

Estratégia de custo: 1 chamada barata por mensagem → só escalona para o modelo caro se
`confidence < 0.8` ou campos obrigatórios nulos. Cache por hash do texto normalizado.
Ver `extract_offer_openrouter` no PoC.

## 2. Três arquiteturas

| | **Opção 1 – GBM tabular** | **Opção 2 – Sobrevivência** | **Opção 3 – LLM + RAG + ciclos** |
|---|---|---|---|
| Pergunta respondida | P(oferta em [t+7, t+15]) por dia | distribuição do tempo até a próxima oferta | P + justificativa em linguagem natural |
| Prós | rápido, flexível, aceita covariáveis (calendário, bônus anterior, concorrência) e múltiplos horizontes | formulação natural; lida com censura (ofertas ainda não ocorridas); dá curva S(t) e janela de maior risco | usa contexto não estruturado (rumores, regras, "última chance"), explicável |
| Contras | rótulos de janelas vizinhas são correlacionados (exige purge/walk-forward); pouca amostra por par | hazards proporcionais raramente valem (ciclos não monotônicos); pouco flexível para sazonalidade forte | não-determinístico, custo/latência, LLM calibra mal probabilidades; difícil de validar |
| Complexidade | Baixa–média | Média | Alta |
| Precisão esperada* | moderada; melhor custo-benefício | moderada; melhor para "quando" | não melhora a precisão sozinha; vale como camada de contexto/ajuste |

\*Estimativas qualitativas. **Não há medição em dados reais** neste repositório. Ordem de grandeza
realista: com ~50 ofertas por par em 3 anos, não espere AUC alto; o PoC mostra isso (abaixo).

Recomendação: **Opção 1 como motor** + feature de hazard da Opção 2 (já no PoC) + **Opção 3 só como
extrator e "explicador"**, nunca como fonte da probabilidade.

## 3. Coleta de dados

**Fontes (por prioridade)**
1. Canais públicos de Telegram de alertas de milhas (Telethon, com conta própria; respeitar limites).
2. Sites do setor com arquivo histórico: Passageiro de Primeira, Melhores Destinos, Melhores Cartões,
   Pontos pra Voar etc. (RSS quando houver; senão HTML).
3. Páginas oficiais de campanha (Livelo, Esfera, Smiles, LATAM Pass, Azul) para confirmar regras e datas.
4. Wayback Machine / CDX API para recuperar 2–3 anos de páginas de campanha.
5. Redes sociais: só via APIs oficiais e dentro dos termos; baixo valor relativo.

**Ferramentas:** `Telethon` (Telegram), `feedparser` (RSS), `httpx` + `selectolax`/`BeautifulSoup` (HTML estático),
`Scrapy` (crawl em escala + dedup + retries), `Playwright` (páginas com JS), `waybackpy`/CDX (histórico),
`APScheduler`/cron (agendamento), `tenacity` (retries). Tempo real: Telethon em modo *event handler*
+ polling RSS a cada 5–10 min.

**Esquema PostgreSQL (SQLite funciona igual, trocando tipos)**
```sql
CREATE TABLE raw_message (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,            -- 'telegram:@canal', 'site:passageirodeprimeira'
  source_msg_id TEXT,
  url TEXT,
  published_at TIMESTAMPTZ NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  text TEXT NOT NULL,
  text_hash CHAR(64) NOT NULL,
  UNIQUE (source, source_msg_id)
);
CREATE TABLE offer (
  id BIGSERIAL PRIMARY KEY,
  origin_program TEXT NOT NULL,    -- livelo | esfera | banco...
  dest_program TEXT NOT NULL,      -- smiles | latam_pass | azul
  event_type TEXT NOT NULL,        -- transfer_bonus | buy_points | boosted_accrual
  bonus_pct NUMERIC(6,2),          -- transferência
  discount_pct NUMERIC(6,2),       -- compra
  base_multiplier NUMERIC(6,2),    -- acúmulo turbinado (ex.: 10 pts/R$)
  start_at TIMESTAMPTZ NOT NULL,   -- INÍCIO REAL da oferta
  end_at TIMESTAMPTZ,
  first_seen_at TIMESTAMPTZ NOT NULL, -- 1º alerta: usar nas features para evitar vazamento
  club_required BOOLEAN, club_tier TEXT, audience TEXT,   -- clube, 'todos'/'segmentada'
  min_points INT, max_points INT,
  conditions JSONB,                -- regras livres
  extractor TEXT, confidence NUMERIC(3,2),
  needs_review BOOLEAN DEFAULT FALSE
);
CREATE TABLE offer_evidence (offer_id BIGINT REFERENCES offer(id), raw_message_id BIGINT REFERENCES raw_message(id),
  PRIMARY KEY (offer_id, raw_message_id));
CREATE INDEX ON offer (origin_program, dest_program, event_type, start_at);
```
Pontos de atenção: (a) deduplicar várias mensagens da mesma oferta (chave = par+tipo+start_at ±1 dia);
(b) distinguir ofertas *segmentadas* (visíveis só a alguns clientes) das gerais; (c) guardar
`first_seen_at` para que o treino use apenas o que era conhecido na data.

## 4. Par inicial e escala

**Par inicial: Livelo → Smiles** (transferência bonificada): maior frequência e maior cobertura
jornalística, portanto mais eventos e rótulos mais confiáveis. Um par × um tipo de evento mantém
o espaço de problemas pequeno.

**Passo a passo de escala**
1. PoC: um par, ≥ 2 anos, validação walk-forward, comparar contra "taxa-base" e contra regra "dias desde a última > média".
2. Generalizar o dataset para chave `(origem, destino, tipo)`; mesma função de features, parametrizada.
3. Um modelo **global** com `origem`, `destino` e `tipo` como categóricas (compartilha força entre pares
   com pouco dado) vs. modelos por par; comparar no walk-forward. Em geral o global vence nos pares raros.
4. Features cruzadas: ofertas recentes de pares irmãos (Livelo→LATAM prediz Livelo→Smiles?), bônus do
   concorrente, calendário (Black Friday, aniversário dos programas, campanhas de companhias).
5. Novos tipos de evento (compra de pontos, acúmulo no varejo): novo extrator + novas colunas já no esquema.
6. MLOps: reprocessamento diário, retreino semanal, monitorar calibração (Brier/reliability), *drift* de
   cadência (ex.: programa muda política de ofertas), alertas ao usuário quando P > limiar calibrado.
7. Só depois: Opção 2 como segundo modelo (curva de tempo) e Opção 3 como camada de explicação.

## 5. PoC

`poc_livelo_smiles.py` (pandas + scikit-learn). Rodar: `python poc_livelo_smiles.py [--shape N] [--csv arquivo.csv]`.
CSV esperado: `start_date,bonus_pct`.

Resultados com **dados sintéticos** (walk-forward, 5 dobras de 4 meses, 608 dias avaliados):

| Gerador | Modelo | AUC | Brier |
|---|---|---|---|
| ruidoso (`--shape 9`) | taxa-base / logreg / GBM | 0,50 / 0,50 / 0,54 | 0,240 / 0,248 / 0,248 |
| regular (`--shape 40`) | taxa-base / logreg / GBM | 0,50 / 0,48 / 0,69 | 0,243 / 0,244 / 0,216 |

Leitura honesta: (1) o pipeline detecta sinal quando existe; (2) com ~50 eventos e ciclo ruidoso, **não há
lift mensurável**, o que é o cenário provável com dados reais de um único par; (3) a regressão logística
falha porque a relação é não-monotônica: a janela [t+7, t+15] exclui o "iminente" (0–6 dias), então estar
muito atrasado *reduz* P(janela). Por isso GBM/hazard em tempo discreto, e não um Cox simples.
Os números acima descrevem o gerador sintético, **não** o comportamento real do mercado.
