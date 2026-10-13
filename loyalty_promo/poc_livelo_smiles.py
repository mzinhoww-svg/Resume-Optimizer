"""PoC: probabilidade de promoção de transferência Livelo -> Smiles nos próximos 7-15 dias.

Abordagem: Opção 1 (GBM tabular com lags/sazonalidade) + feature de "hazard" da Opção 2
(razão entre dias desde a última oferta e o intervalo típico). Validação temporal.

Uso:
    python poc_livelo_smiles.py                 # dados sintéticos
    python poc_livelo_smiles.py --csv ofertas.csv   # colunas: start_date,bonus_pct
Dependências: pandas, numpy, scikit-learn
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

H_MIN, H_MAX = 7, 15  # janela-alvo em dias à frente
KEY_DATES = {"black_friday": (11, 24), "dia_consumidor": (3, 15), "aniversario_livelo": (9, 1)}


# ---------------------------------------------------------------- 1. Ingestão
def synthetic_offers(seed: int = 7, years: int = 3, end: str = "2026-10-01", shape: float = 9.0) -> pd.DataFrame:
    """Simula histórico: intervalos ~Gamma, mais frequentes em nov/jul/mar, bônus 60-120%."""
    rng = np.random.default_rng(seed)
    t, stop = pd.Timestamp(end) - pd.DateOffset(years=years), pd.Timestamp(end)
    rows = []
    while t < stop:
        season = {11: 0.55, 12: 0.8, 7: 0.75, 3: 0.8}.get(t.month, 1.0)
        gap = max(3, int(rng.gamma(shape=shape, scale=25 / shape) * season))  # média ~25d
        t += pd.Timedelta(days=gap)
        if t >= stop:
            break
        bonus = int(rng.choice([60, 80, 90, 100, 120], p=[.1, .35, .15, .3, .1]))
        rows.append((t.normalize(), bonus))
    return pd.DataFrame(rows, columns=["start_date", "bonus_pct"])


def load_offers(csv: str | None, shape: float = 9.0) -> pd.DataFrame:
    if not csv:
        return synthetic_offers(shape=shape)
    df = pd.read_csv(csv, parse_dates=["start_date"])
    return df.sort_values("start_date").drop_duplicates("start_date").reset_index(drop=True)


# ----------------------------------------------------- 2. Engenharia de atributos
def build_dataset(offers: pd.DataFrame, ref_date: str | pd.Timestamp = "2026-10-13") -> pd.DataFrame:
    days = pd.date_range(offers.start_date.min(), pd.Timestamp(ref_date), freq="D")
    df = pd.DataFrame({"date": days})
    starts = offers.set_index("start_date")
    df["event"] = df.date.isin(starts.index).astype(int)
    ev = df.event.to_numpy()
    n = len(df)

    # Alvo: houve início de oferta em (t+7 .. t+15]?  (só usa o futuro para o rótulo)
    cs = np.concatenate([[0], np.cumsum(ev)])
    idx = np.arange(n)
    hi, lo = np.minimum(idx + H_MAX + 1, n), np.minimum(idx + H_MIN, n)
    df["y"] = ((cs[hi] - cs[lo]) > 0).astype(int)
    df.loc[idx + H_MAX >= n, "y"] = -1  # janela incompleta -> descartada

    # Atributos: apenas passado/presente (sem vazamento)
    last_idx = pd.Series(np.where(ev == 1, idx, np.nan)).ffill().to_numpy()
    df["days_since_last"] = idx - last_idx
    df["last_bonus"] = starts.bonus_pct.reindex(df.date).ffill().to_numpy()

    gaps = offers.start_date.diff().dt.days
    gap_by_date = pd.Series(gaps.to_numpy(), index=offers.start_date).reindex(df.date)
    df["last_gap"] = gap_by_date.ffill().to_numpy()
    recent = pd.Series(gaps.to_numpy(), index=offers.start_date)
    mean5 = recent.rolling(5, min_periods=2).mean().reindex(df.date).ffill()
    std5 = recent.rolling(5, min_periods=2).std().reindex(df.date).ffill()
    df["mean_gap_5"], df["std_gap_5"] = mean5.to_numpy(), std5.to_numpy()
    df["hazard_ratio"] = df.days_since_last / df.mean_gap_5  # >1 => "atrasada"

    for w in (30, 90, 180):
        df[f"n_offers_{w}d"] = pd.Series(ev).rolling(w, min_periods=1).sum().to_numpy()

    df["month_sin"] = np.sin(2 * np.pi * df.date.dt.month / 12)
    df["month_cos"] = np.cos(2 * np.pi * df.date.dt.month / 12)
    df["dow"] = df.date.dt.dayofweek
    df["dom"] = df.date.dt.day
    for name, (m, d) in KEY_DATES.items():
        ref = df.date.apply(lambda x: pd.Timestamp(year=x.year, month=m, day=d))
        delta = (ref - df.date).dt.days
        delta = delta.where(delta >= -3, delta + 365)  # próxima ocorrência
        df[f"d_to_{name}"] = delta.clip(upper=120)
    return df.dropna(subset=FEATURES).reset_index(drop=True)


FEATURES = ["days_since_last", "last_bonus", "last_gap", "mean_gap_5", "std_gap_5", "hazard_ratio",
            "n_offers_30d", "n_offers_90d", "n_offers_180d", "month_sin", "month_cos", "dow", "dom",
            "d_to_black_friday", "d_to_dia_consumidor", "d_to_aniversario_livelo"]


# --------------------------------------------------- 3. Modelo e validação temporal
def _gbm() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(max_depth=2, learning_rate=0.03, max_iter=120,
                                          min_samples_leaf=40, l2_regularization=5.0, random_state=0)


LR_FEATS = ["days_since_last", "hazard_ratio", "month_sin", "month_cos"]


def evaluate(df: pd.DataFrame, n_folds: int = 5, fold_months: int = 4) -> HistGradientBoostingClassifier:
    """Walk-forward (origem rolante): treina no passado, testa nos próximos `fold_months` meses.
    Há purge de H_MAX dias entre treino e teste, pois os rótulos olham até 15 dias à frente."""
    data = df[df.y >= 0]
    end = data.date.max()
    preds: dict[str, list] = {"base_rate": [], "logreg": [], "gbm": []}
    ys = []
    for k in range(n_folds, 0, -1):
        t1 = end - pd.DateOffset(months=fold_months * (k - 1))
        t0 = t1 - pd.DateOffset(months=fold_months)
        tr, te = data[data.date < t0 - pd.Timedelta(days=H_MAX)], data[(data.date >= t0) & (data.date < t1)]
        if tr.y.nunique() < 2 or te.empty:
            continue
        lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5)).fit(tr[LR_FEATS], tr.y)
        preds["base_rate"].append(np.full(len(te), tr.y.mean()))
        preds["logreg"].append(lr.predict_proba(te[LR_FEATS])[:, 1])
        preds["gbm"].append(_gbm().fit(tr[FEATURES], tr.y).predict_proba(te[FEATURES])[:, 1])
        ys.append(te.y.to_numpy())
    y = np.concatenate(ys)
    print(f"walk-forward: {len(ys)} dobras, {len(y)} dias avaliados, prevalência={y.mean():.1%}")
    print(f"{'modelo':<12}{'AUC':>7}{'PR-AUC':>8}{'Brier':>8}")
    for k, v in preds.items():
        v = np.concatenate(v)
        auc = 0.5 if k == "base_rate" else roc_auc_score(y, v)
        print(f"{k:<12}{auc:7.3f}{average_precision_score(y, v):8.3f}{brier_score_loss(y, v):8.3f}")
    return _gbm().fit(data[FEATURES], data.y)  # modelo final: todo o histórico rotulado


# --------------------------------------------------------------- 4. Previsão hoje
def predict_today(model, df: pd.DataFrame) -> None:
    row = df.iloc[[-1]]
    prob = model.predict_proba(row[FEATURES])[0, 1]
    d0 = row.date.iloc[0]
    print(f"\nLivelo -> Smiles | referência {d0:%d/%m/%Y} | dias desde a última oferta: "
          f"{int(row.days_since_last.iloc[0])}")
    print(f"P(nova promo entre {d0 + pd.Timedelta(days=H_MIN):%d/%m} e "
          f"{d0 + pd.Timedelta(days=H_MAX):%d/%m}) = {prob:.1%}")


# -------------------------- 5. (opcional) extração de ofertas via OpenRouter ----
def extract_offer_openrouter(text: str, model: str = "anthropic/claude-3.5-haiku") -> dict:
    """Transforma texto livre de alerta em JSON estruturado. Requer OPENROUTER_API_KEY."""
    import json
    import os
    import urllib.request

    body = {"model": model, "response_format": {"type": "json_object"}, "temperature": 0,
            "messages": [{"role": "system", "content":
                          "Extraia JSON: {origem,destino,tipo(transferencia|compra|acumulo),"
                          "bonus_pct,inicio,fim,clube_exigido,fonte_confiavel}. Use null se ausente."},
                         {"role": "user", "content": text}]}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                                  "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--shape", type=float, default=9.0, help="regularidade do gerador sintético (maior = mais regular)")
    args = ap.parse_args()
    offers = load_offers(args.csv, args.shape)
    print(f"{len(offers)} ofertas | {offers.start_date.min():%Y-%m-%d} -> {offers.start_date.max():%Y-%m-%d}")
    df = build_dataset(offers)
    model = evaluate(df)
    predict_today(model, df)


if __name__ == "__main__":
    main()
