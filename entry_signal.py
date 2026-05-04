"""
Options Trading — Combined Entry Signal (Phase 2 + Phase 3)
============================================================
Trains both the direction model (Phase 2) and IV expansion model (Phase 3)
on historical data, then outputs a single combined entry recommendation.

Decision framework:
  Win + Expansion   → Strong entry: direction and IV both favorable
  Win + Contraction → Caution: direction good but IV crush risk
  Loss + Expansion  → Stay out: vol rising but no directional edge
  Loss + Contraction → Stay out: both signals unfavorable

Requirements:
    pip install yfinance pandas scikit-learn
"""

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
TICKER         = "AMD"
START_DATE     = "2018-01-01"
END_DATE       = ""  # set automatically from CSV
INDICATORS_CSV = f"{TICKER.lower()}_indicators.csv"

HV_WINDOW           = 20
IV_RANK_WINDOW      = 252
P2_FORWARD_DAYS     = 15    # Phase 2: direction window
P3_FORWARD_DAYS     = 10    # Phase 3: IV expansion window
WIN_THRESHOLD       = 0.05  # Phase 2: 5% gain = win
EXPANSION_THRESHOLD = 0.10  # Phase 3: 10% HV rise = expansion
TEST_SIZE           = 0.20
P2_THRESHOLD        = 0.55  # Direction signal cutoff (best precision from Phase 2)
P3_THRESHOLD        = 0.60  # IV expansion cutoff (best precision from Phase 3)
RANDOM_STATE        = 42


# ─────────────────────────────────────────
# 1. LOAD BASE INDICATORS
# ─────────────────────────────────────────
def load_indicators(path):
    global TICKER, START_DATE, END_DATE
    print(f"Loading indicators from {path}...")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df = df.sort_index()
    if "Adj Close" in df.columns:
        df.drop(columns=["Adj Close"], inplace=True)
    if "Ticker" in df.columns:
        TICKER = df["Ticker"].iloc[0]
        df.drop(columns=["Ticker"], inplace=True)
    START_DATE = df.index.min().strftime("%Y-%m-%d")
    END_DATE   = df.index.max().strftime("%Y-%m-%d")
    print(f"  → Ticker: {TICKER} | {START_DATE} to {END_DATE}")
    print(f"  → {len(df)} rows, {len(df.columns)} columns\n")
    return df


# ─────────────────────────────────────────
# 2. FEATURE ENGINEERING
# ─────────────────────────────────────────
def build_features(df):
    close = df["Close"]

    # HV and IV features
    log_ret = np.log(close / close.shift(1))
    df["HV_20"] = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)
    hv_high = df["HV_20"].rolling(IV_RANK_WINDOW).max()
    hv_low  = df["HV_20"].rolling(IV_RANK_WINDOW).min()
    df["IV_rank"]    = (df["HV_20"] - hv_low) / (hv_high - hv_low)
    df["IV_pct"]     = df["HV_20"].rolling(IV_RANK_WINDOW).apply(
        lambda x: (x[:-1] < x[-1]).mean(), raw=True
    )
    df["HV_chg_5d"]  = df["HV_20"].pct_change(5)
    df["HV_chg_10d"] = df["HV_20"].pct_change(10)
    df["HV_vs_ma20"] = df["HV_20"] / df["HV_20"].rolling(20).mean() - 1

    # VIX
    raw = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)
    raw.columns = raw.columns.get_level_values(0)
    vix = raw[["Close"]].rename(columns={"Close": "VIX"})
    vix["VIX_chg_5d"]  = vix["VIX"].pct_change(5)
    vix["VIX_vs_ma20"] = vix["VIX"] / vix["VIX"].rolling(20).mean() - 1
    df = df.join(vix, how="left")
    df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]] = df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]].ffill()

    # SOX relative strength
    raw = yf.download("^SOX", start=START_DATE, end=END_DATE, progress=False)
    raw.columns = raw.columns.get_level_values(0)
    sox = raw[["Close"]].rename(columns={"Close": "SOX"})
    df = df.join(sox, how="left")
    df["SOX"] = df["SOX"].ffill()
    for window in [5, 20]:
        df[f"SOX_RS_{window}d"] = close.pct_change(window) - df["SOX"].pct_change(window)
    df.drop(columns=["SOX"], inplace=True)

    # Earnings proximity
    ticker = yf.Ticker(TICKER)
    ed = []
    try:
        dates = ticker.get_earnings_dates(limit=20)
        if dates is not None and len(dates) > 0:
            idx = pd.DatetimeIndex(dates.index)
            if idx.tz is not None:
                idx = idx.tz_convert(None)
            ed = sorted(idx.normalize().unique())
    except Exception:
        pass
    if ed:
        def _days_to_next(date):
            future = [e for e in ed if e >= date]
            return (future[0] - date).days if future else 90
        df["Days_to_earnings"] = [_days_to_next(d) for d in df.index]
    else:
        df["Days_to_earnings"] = 45

    # Normalize price-level features
    for period in [20, 50, 200]:
        col = f"MA_{period}"
        if col in df.columns:
            df[f"price_vs_ma{period}"] = close / df[col] - 1
    df.drop(columns=[c for c in df.columns if c.startswith("MA_")], inplace=True)

    for period in [8, 21, 89]:
        col = f"EMA_{period}"
        if col in df.columns:
            df[f"price_vs_ema{period}"] = close / df[col] - 1
    df.drop(columns=[c for c in df.columns if c.startswith("EMA_")], inplace=True)

    for band, label in [("KC_upper", "kc_upper"), ("KC_middle", "kc_mid"), ("KC_lower", "kc_lower")]:
        if band in df.columns:
            df[f"price_vs_{label}"] = close / df[band] - 1
            df.drop(columns=[band], inplace=True)

    for col in ["MACD", "MACD_signal", "MACD_hist"]:
        if col in df.columns:
            df[f"{col}_norm"] = df[col] / close
            df.drop(columns=[col], inplace=True)

    if "OBV" in df.columns:
        df["OBV_chg_5d"] = df["OBV"].pct_change(5)
        df.drop(columns=["OBV"], inplace=True)

    print("Features built.\n")
    return df


# ─────────────────────────────────────────
# 3. TRAIN MODELS
# ─────────────────────────────────────────
def train(df, target_col):
    exclude = {"Open", "High", "Low", "Close", "Volume", target_col}
    feature_cols = [c for c in df.columns if c not in exclude]

    df_model = df[feature_cols + [target_col]].dropna()
    X = df_model[feature_cols]
    y = df_model[target_col]

    split_idx  = int(len(X) * (1 - TEST_SIZE))
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    clf = LogisticRegression(C=0.1, class_weight="balanced",
                             max_iter=1000, random_state=RANDOM_STATE)
    clf.fit(X_train_s, y_train)

    train_acc = (clf.predict(X_train_s) == y_train).mean()
    test_acc  = (clf.predict(X_test_s)  == y_test).mean()

    return clf, scaler, feature_cols, train_acc, test_acc


def get_current_prob(df_full, clf, scaler, feature_cols):
    latest = df_full[feature_cols].dropna().iloc[-1]
    X = pd.DataFrame([latest], columns=feature_cols)
    return clf.predict_proba(scaler.transform(X))[0, 1]


# ─────────────────────────────────────────
# 4. COMBINED SIGNAL OUTPUT
# ─────────────────────────────────────────
def print_combined_signal(df_full, direction_prob, expansion_prob, iv_rank, iv_pct, hv_20):
    latest_date = df_full.dropna().index[-1].strftime("%Y-%m-%d")

    dir_signal = direction_prob >= P2_THRESHOLD
    exp_signal = expansion_prob >= P3_THRESHOLD

    iv_regime = "Low IV" if iv_rank < 0.33 else "High IV" if iv_rank > 0.67 else "Mid IV"

    if dir_signal and exp_signal:
        recommendation = "STRONG ENTRY"
        detail = "Direction and IV both favorable — options cheap and vol likely rising."
    elif dir_signal and not exp_signal:
        recommendation = "CAUTION"
        detail = "Direction favorable but IV crush risk — consider smaller size or wait for vol to fall."
    elif not dir_signal and exp_signal:
        recommendation = "STAY OUT"
        detail = "Vol rising but no directional edge — wait for direction signal."
    else:
        recommendation = "STAY OUT"
        detail = "Direction and IV both unfavorable — no entry."

    w = 54
    print(f"\n{'═'*w}")
    print(f"  COMBINED ENTRY SIGNAL — {TICKER} as of {latest_date}")
    print(f"{'═'*w}")
    print(f"\n  DIRECTION (Phase 2)  [threshold: {P2_THRESHOLD}]")
    print(f"  Win Probability:    {direction_prob:.1%}")
    print(f"  Signal:             {'WIN ✓' if dir_signal else 'NO SIGNAL ✗'}")
    print(f"\n  IV TIMING (Phase 3)  [threshold: {P3_THRESHOLD}]")
    print(f"  HV (20-day):        {hv_20:.1%}")
    print(f"  IV Rank:            {iv_rank:.2f}  ({iv_regime})")
    print(f"  IV Percentile:      {iv_pct:.1%}")
    print(f"  Expansion Prob:     {expansion_prob:.1%}")
    print(f"  Signal:             {'EXPANSION ✓' if exp_signal else 'CONTRACTION ✗'}")
    print(f"\n  {'─'*w}")
    print(f"  RECOMMENDATION:     {recommendation}")
    print(f"  {detail}")
    print(f"{'═'*w}\n")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    ticker_in = input(f"  Ticker [{TICKER}]: ").strip().upper()
    if ticker_in:
        TICKER         = ticker_in
        INDICATORS_CSV = f"{TICKER.lower()}_indicators.csv"

    df = load_indicators(INDICATORS_CSV)
    df_full = build_features(df)

    # Phase 2 — direction target
    df_p2 = df_full.copy()
    future_close = df_p2["Close"].shift(-P2_FORWARD_DAYS)
    df_p2["direction_target"] = ((future_close / df_p2["Close"] - 1) >= WIN_THRESHOLD).astype(int)
    df_p2 = df_p2.iloc[:-P2_FORWARD_DAYS]
    clf2, scaler2, fcols2, tr2, te2 = train(df_p2, "direction_target")
    print(f"Phase 2 (direction)  — train: {tr2:.1%}  test: {te2:.1%}")

    # Phase 3 — IV expansion target
    df_p3 = df_full.copy()
    future_hv = df_p3["HV_20"].shift(-P3_FORWARD_DAYS)
    df_p3["iv_target"] = ((future_hv / df_p3["HV_20"] - 1) >= EXPANSION_THRESHOLD).astype(int)
    df_p3 = df_p3.iloc[:-P3_FORWARD_DAYS]
    clf3, scaler3, fcols3, tr3, te3 = train(df_p3, "iv_target")
    print(f"Phase 3 (IV timing)  — train: {tr3:.1%}  test: {te3:.1%}\n")

    # Current signals
    direction_prob = get_current_prob(df_full, clf2, scaler2, fcols2)
    expansion_prob = get_current_prob(df_full, clf3, scaler3, fcols3)

    latest = df_full[["HV_20", "IV_rank", "IV_pct"]].dropna().iloc[-1]
    print_combined_signal(
        df_full,
        direction_prob,
        expansion_prob,
        latest["IV_rank"],
        latest["IV_pct"],
        latest["HV_20"],
    )