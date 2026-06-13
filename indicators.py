"""
AMD Trading Indicator Pipeline - Phase 1
=========================================
Pulls AMD historical data and calculates all indicators from your strategy:
- RSI (6, 14, 23)
- MA / EMA (configurable periods)
- Keltner Channels
- On-Balance Volume (OBV)
- MACD
- Stochastic Oscillator

Requirements:
    pip install yfinance pandas ta matplotlib

Usage:
    python amd_indicators.py
"""

import sys
import datetime
import os
import yfinance as yf
import pandas as pd
import ta
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import MaxNLocator, FuncFormatter

from modules.massive import IV_COLS, get_chain_summary

# ─────────────────────────────────────────
# CONFIG — adjust these to your preference
# ─────────────────────────────────────────
# TICKER       = "AMD"
START_DATE   = "1792-05-17"
END_DATE     = datetime.date.today().strftime("%Y-%m-%d")
DATA_DIR     = "data"

RSI_PERIODS  = [6, 14, 23]         # RSI periods
MA_PERIODS   = [20, 50, 100, 200]       # Simple moving averages
EMA_PERIODS  = [8, 21, 34, 55, 89]             # Exponential moving averages
KC_EMA       = 21                  # Keltner Channel EMA period
KC_ATR       = 14                  # Keltner Channel ATR period
KC_MULT      = 2.0                 # Keltner Channel multiplier
STOCH_K      = 14                  # Stochastic %K period
STOCH_D      = 3                   # Stochastic %D smoothing
STOCH_SMOOTH = 3                   # Stochastic smoothing


# ─────────────────────────────────────────
# 1. FETCH DATA
# ─────────────────────────────────────────
def fetch_data(ticker, start, end):
    print(f"Fetching {ticker} data from {start} to {end}...")
    df = yf.download(ticker, start=start, end=end, progress=False)
    df.columns = df.columns.get_level_values(0)
    df.dropna(inplace=True)
    print(f"  → {len(df)} trading days loaded\n")
    return df


# ─────────────────────────────────────────
# 1B. TRADIER PRICE AUGMENT (same-day close + gap backfill)
# ─────────────────────────────────────────
def augment_recent_prices_from_tradier(df, ticker):
    """Fill today's bar after the close + backfill recent sessions yfinance skipped.

    yfinance is fetched with an exclusive end date (END_DATE = today), so today's
    bar is never requested — without this, every signal runs on yesterday's close
    at best. The Tradier quote's 'close' field is null while the session is open
    and populates at the bell, so it acts as a completed-session latch; trade_date
    must also be today (guards a pre-open run picking up the prior session).

    Tradier prices are split/dividend-unadjusted vs yfinance's adjusted series.
    Acceptable: stamped rows are replaced by the next run's fresh yfinance fetch
    (only IV columns are merge-preserved in harvest_iv_snapshot).

    Must run BEFORE add_indicators so the stamped bars flow into RSI/MA/etc.
    Graceful: any failure leaves df unchanged."""
    try:
        from modules.tradier import get_daily_quote, get_daily_history

        now_et = pd.Timestamp.now(tz="America/New_York")
        today  = pd.Timestamp(now_et.date())
        ohlcv  = ["Open", "High", "Low", "Close", "Volume"]

        if now_et.weekday() < 5 and now_et.hour >= 16 and today not in df.index:
            q = get_daily_quote(ticker) or {}
            tdate = q.get("trade_date")
            tdate_is_today = (
                tdate is not None
                and pd.Timestamp(tdate, unit="ms", tz="UTC")
                      .tz_convert("America/New_York").date() == now_et.date()
            )
            if tdate_is_today and all(q.get(k) is not None for k in ["open", "high", "low", "close"]):
                df.loc[today, ohlcv] = [
                    float(q["open"]), float(q["high"]), float(q["low"]),
                    float(q["close"]), float(q.get("volume") or 0),
                ]
                df = df.sort_index()
                print(f"  Today's close stamped from Tradier: ${float(q['close']):.2f} (post-4PM ET)")

        # Trailing-week holes (yfinance can lag a bar — e.g. 2026-06-10 was
        # missing the morning after). Days absent at Tradier too are holidays.
        recent  = pd.bdate_range(end=today - pd.Timedelta(days=1), periods=5)
        missing = [d for d in recent if d not in df.index]
        if missing:
            bars = {pd.Timestamp(b["date"]): b
                    for b in get_daily_history(ticker,
                                               missing[0].strftime("%Y-%m-%d"),
                                               missing[-1].strftime("%Y-%m-%d"))}
            filled = []
            for d in missing:
                b = bars.get(d)
                if b is None or any(b.get(k) is None for k in ["open", "high", "low", "close"]):
                    continue
                df.loc[d, ohlcv] = [
                    float(b["open"]), float(b["high"]), float(b["low"]),
                    float(b["close"]), float(b.get("volume") or 0),
                ]
                filled.append(str(d.date()))
            if filled:
                df = df.sort_index()
                print(f"  Backfilled {len(filled)} missing session(s) from Tradier: {', '.join(filled)}")
    except Exception as e:
        print(f"  Tradier price augment skipped ({e})")
    return df


# ─────────────────────────────────────────
# 2. CALCULATE INDICATORS
# ─────────────────────────────────────────
def add_indicators(df):
    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"]

    # --- RSI ---
    for period in RSI_PERIODS:
        df[f"RSI_{period}"] = ta.momentum.RSIIndicator(close, window=period).rsi()

    # --- Simple Moving Averages ---
    for period in MA_PERIODS:
        df[f"MA_{period}"] = ta.trend.SMAIndicator(close, window=period).sma_indicator()

    # --- Exponential Moving Averages ---
    for period in EMA_PERIODS:
        df[f"EMA_{period}"] = ta.trend.EMAIndicator(close, window=period).ema_indicator()

    # --- Keltner Channels ---
    kc = ta.volatility.KeltnerChannel(
        high, low, close,
        window=KC_EMA,
        window_atr=KC_ATR,
        multiplier=KC_MULT
    )
    df["KC_upper"]  = kc.keltner_channel_hband()
    df["KC_middle"] = kc.keltner_channel_mband()
    df["KC_lower"]  = kc.keltner_channel_lband()

    # --- On-Balance Volume ---
    df["OBV"] = ta.volume.OnBalanceVolumeIndicator(close, volume).on_balance_volume()

    # --- MACD ---
    macd = ta.trend.MACD(close)
    df["MACD"]        = macd.macd()
    df["MACD_signal"] = macd.macd_signal()
    df["MACD_hist"]   = macd.macd_diff()

    # --- Stochastic Oscillator ---
    stoch = ta.momentum.StochasticOscillator(
        high, low, close,
        window=STOCH_K,
        smooth_window=STOCH_D
    )
    df["Stoch_K"] = stoch.stoch()
    df["Stoch_D"] = stoch.stoch_signal()

    # --- Overnight Gap ---
    df["gap_pct"]    = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1)
    df["gap_ma_5d"]  = df["gap_pct"].rolling(5).mean()
    df["gap_vol_5d"] = df["gap_pct"].abs().rolling(5).mean()

    print("Indicators calculated:")
    indicator_cols = [c for c in df.columns if c not in ["Open","High","Low","Close","Adj Close","Volume"]]
    for col in indicator_cols:
        print(f"  ✓ {col}")
    print()

    return df


# ─────────────────────────────────────────
# 3. SIGNAL SUMMARY (latest bar)
# ─────────────────────────────────────────
def print_signal_summary(df):
    
    latest = df.iloc[-1]
    date   = df.index[-1].strftime("%Y-%m-%d")

    print(f"{'═'*50}")
    print(f"  SIGNAL SUMMARY — {TICKER} as of {date}")
    print(f"{'═'*50}")
    prev_close = df["Close"].iloc[-2] if len(df) > 1 else latest["Open"]
    chg     = latest["Close"] - prev_close
    chg_pct = (chg / prev_close * 100) if prev_close else 0.0
    arrow   = "▲" if chg >= 0 else "▼"
    print(f"  Close:        ${latest['Close']:.2f}   {arrow} {chg:+.2f} ({chg_pct:+.2f}%)")
    print(f"  OHLC:         O ${latest['Open']:.2f}  H ${latest['High']:.2f}  "
          f"L ${latest['Low']:.2f}  C ${latest['Close']:.2f}")
    print()
    for period in RSI_PERIODS:
        val = latest[f'RSI_{period}']
        status = '⚠ Overbought' if val > 70 else '⚠ Oversold' if val < 30 else '─ Neutral'
        print(f"  RSI-{period}:{'       ' if period < 10 else '      '}{val:.1f}  {status}")
    print()
    kc_pos = "Above upper" if latest["Close"] > latest["KC_upper"] else \
             "Below lower" if latest["Close"] < latest["KC_lower"] else "Inside"
    print(f"  KC Position:  {kc_pos}  (U:{latest['KC_upper']:.2f} / M:{latest['KC_middle']:.2f} / L:{latest['KC_lower']:.2f})")
    print()
    macd_sig = "Bullish" if latest["MACD"] > latest["MACD_signal"] else "Bearish"
    print(f"  MACD:         {latest['MACD']:.3f} | Signal: {latest['MACD_signal']:.3f}  → {macd_sig}")
    print()
    stoch_sig = "Overbought" if latest["Stoch_K"] > 80 else "Oversold" if latest["Stoch_K"] < 20 else "Neutral"
    print(f"  Stoch %K:     {latest['Stoch_K']:.1f} | %D: {latest['Stoch_D']:.1f}  → {stoch_sig}")
    print()
    print(f"  OBV:          {latest['OBV']:,.0f}")
    print(f"{'═'*50}\n")


# ─────────────────────────────────────────
# 4. PLOT DASHBOARD
# ─────────────────────────────────────────
def plot_dashboard(df):
    # Use last 6 months for readability
    plot_df = df[df.index >= df.index.max() - pd.Timedelta(days=365*3)]

    fig = plt.figure(figsize=(16, 14), facecolor="#0d1117")
    fig.suptitle(f"{TICKER} — Indicator Dashboard", color="white", fontsize=14, y=0.98)

    gs = GridSpec(5, 1, figure=fig, hspace=0.05,
                  height_ratios=[3, 1, 1, 1, 1])

    style = dict(color="#e6edf3")

    # ── Panel 1: Price (hollow candles) + MA/EMA + KC ──
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor("#0d1117")

    # Draw hollow candlesticks with gap-based coloring (matches Webull)
    # Color = today's close vs previous close (green if up, red if down)
    # Body shape = today's close vs today's open (hollow if up, filled if down)
    width = 0.6
    closes = plot_df["Close"].values
    for i, (idx, row) in enumerate(plot_df.iterrows()):
        o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
        prev_close = closes[i - 1] if i > 0 else o
        # Color based on close vs previous close
        color = "#3fb950" if c >= prev_close else "#f85149"
        # Hollow vs filled based on close vs open
        hollow = c >= o
        # High/low wick
        ax1.plot([i, i], [l, h], color=color, lw=0.8, zorder=1)
        # Body
        body_bottom = min(o, c)
        body_height = abs(c - o) if abs(c - o) > 0 else 0.01
        rect = plt.Rectangle(
            (i - width/2, body_bottom), width, body_height,
            edgecolor=color,
            facecolor="none" if hollow else color,
            lw=0.8, zorder=2,
            alpha=1.0 if hollow else 0.8
        )
        ax1.add_patch(rect)

    # Convert index to integer positions for overlays
    x = range(len(plot_df))
    ax1.fill_between(x, plot_df["KC_upper"].values, plot_df["KC_lower"].values,
                     alpha=0.1, color="#f78166", label="Keltner Band")
    ax1.plot(x, plot_df["KC_upper"].values,  color="#f78166", lw=0.6, ls="--")
    ax1.plot(x, plot_df["KC_middle"].values, color="#f78166", lw=0.8, label="KC Mid")
    ax1.plot(x, plot_df["KC_lower"].values,  color="#f78166", lw=0.6, ls="--")
    for p, c in zip(MA_PERIODS, ["#ffa657", "#3fb950", "#bc8cff"]):
        col = f"MA_{p}"
        if col in plot_df.columns:
            ax1.plot(x, plot_df[col].values, color=c, lw=0.8, label=f"MA{p}")

    # Zoom-aware date labels on integer x-axis (candles need integer positions
    # to avoid weekend gaps). MaxNLocator picks ~12 integer ticks across the
    # current view; FuncFormatter converts to dates with format adaptive to span.
    def _idx_to_date(pos, _):
        i = int(round(pos))
        if not (0 <= i < len(plot_df)):
            return ""
        view_lo, view_hi = ax1.get_xlim()
        span = view_hi - view_lo
        if span > 500:       # > ~2 years visible
            fmt = "%b '%y"
        elif span > 60:      # ~3 months to 2 years
            fmt = "%Y-%m-%d"
        else:                # zoomed in tight
            fmt = "%b %d"
        return plot_df.index[i].strftime(fmt)

    ax1.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=12))
    ax1.xaxis.set_major_formatter(FuncFormatter(_idx_to_date))
    ax1.set_xlim(-1, len(plot_df))
    ax1.set_ylabel("Price", **style)
    ax1.legend(fontsize=7, loc="upper left", facecolor="#161b22", labelcolor="white")
    ax1.tick_params(colors="#8b949e", labelbottom=False)
    ax1.spines[:].set_color("#30363d")

    # ── Latest-bar OHLC readout (upper-right) ──
    last      = plot_df.iloc[-1]
    last_date = plot_df.index[-1].strftime("%Y-%m-%d")
    o, h, l, c = last["Open"], last["High"], last["Low"], last["Close"]
    prev_c = plot_df["Close"].iloc[-2] if len(plot_df) > 1 else o
    chg    = c - prev_c
    chg_pct = (chg / prev_c * 100) if prev_c else 0.0
    up      = chg >= 0
    chg_col = "#3fb950" if up else "#f85149"
    arrow   = "▲" if up else "▼"
    ohlc_txt = (
        f"{last_date}\n"
        f"O {o:.2f}   H {h:.2f}\n"
        f"L {l:.2f}   C {c:.2f}\n"
        f"{arrow} {chg:+.2f} ({chg_pct:+.2f}%)"
    )
    ax1.text(
        0.985, 0.97, ohlc_txt, transform=ax1.transAxes,
        ha="right", va="top", fontsize=8.5, family="monospace",
        color="#e6edf3", linespacing=1.5,
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#161b22",
                  edgecolor=chg_col, linewidth=1.2),
    )

    # ── Panel 2: RSI triple ──
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.set_facecolor("#0d1117")
    ax2.plot(x, plot_df["RSI_6"].values,  color="#ffa657", lw=0.9, label="RSI-6")
    ax2.plot(x, plot_df["RSI_14"].values, color="#58a6ff", lw=0.9, label="RSI-14")
    ax2.plot(x, plot_df["RSI_23"].values, color="#3fb950", lw=0.9, label="RSI-23")
    ax2.axhline(70, color="#f85149", lw=0.5, ls="--")
    ax2.axhline(30, color="#3fb950", lw=0.5, ls="--")
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI", **style)
    ax2.legend(fontsize=7, loc="upper left", facecolor="#161b22", labelcolor="white")
    ax2.tick_params(colors="#8b949e", labelbottom=False)
    ax2.spines[:].set_color("#30363d")

    # ── Panel 3: MACD ──
    ax3 = fig.add_subplot(gs[2], sharex=ax1)
    ax3.set_facecolor("#0d1117")
    ax3.plot(x, plot_df["MACD"].values,        color="#58a6ff", lw=0.9, label="MACD")
    ax3.plot(x, plot_df["MACD_signal"].values, color="#ffa657", lw=0.9, label="Signal")
    colors = ["#3fb950" if v >= 0 else "#f85149" for v in plot_df["MACD_hist"]]
    ax3.bar(x, plot_df["MACD_hist"].values, color=colors, alpha=0.5, width=0.8)
    ax3.axhline(0, color="#8b949e", lw=0.5)
    ax3.set_ylabel("MACD", **style)
    ax3.legend(fontsize=7, loc="upper left", facecolor="#161b22", labelcolor="white")
    ax3.tick_params(colors="#8b949e", labelbottom=False)
    ax3.spines[:].set_color("#30363d")

    # ── Panel 4: Stochastic ──
    ax4 = fig.add_subplot(gs[3], sharex=ax1)
    ax4.set_facecolor("#0d1117")
    ax4.plot(x, plot_df["Stoch_K"].values, color="#58a6ff", lw=0.9, label="%K")
    ax4.plot(x, plot_df["Stoch_D"].values, color="#ffa657", lw=0.9, label="%D")
    ax4.axhline(80, color="#f85149", lw=0.5, ls="--")
    ax4.axhline(20, color="#3fb950", lw=0.5, ls="--")
    ax4.set_ylim(0, 100)
    ax4.set_ylabel("Stoch", **style)
    ax4.legend(fontsize=7, loc="upper left", facecolor="#161b22", labelcolor="white")
    ax4.tick_params(colors="#8b949e", labelbottom=False)
    ax4.spines[:].set_color("#30363d")

    # ── Panel 5: OBV ──
    ax5 = fig.add_subplot(gs[4], sharex=ax1)
    ax5.set_facecolor("#0d1117")
    ax5.plot(x, plot_df["OBV"].values, color="#bc8cff", lw=0.9, label="OBV")
    ax5.set_ylabel("OBV", **style)
    ax5.legend(fontsize=7, loc="upper left", facecolor="#161b22", labelcolor="white")
    ax5.tick_params(colors="#8b949e")
    ax5.spines[:].set_color("#30363d")
    plt.setp(ax5.get_xticklabels(), rotation=30, ha="right",
             color="#8b949e", fontsize=7)

    plt.savefig(os.path.join(DATA_DIR, f"{TICKER.lower()}_dashboard.png"), dpi=150,
                bbox_inches="tight", facecolor="#0d1117")
    print(f"Chart saved -> {os.path.join(DATA_DIR, f'{TICKER.lower()}_dashboard.png')}")
    if input("Show chart? (y/n): ").strip().lower() == "y":
        plt.show()


# ─────────────────────────────────────────
# 5. OPTIONS CHAIN HARVEST (Massive)
# ─────────────────────────────────────────
def harvest_iv_snapshot(df, ticker, csv_path):
    """Append today's chain snapshot summary (atm_iv, skew, term, p/c OI) to today's
    row. Past rows stay NaN until the BS-inversion backfill (S11) populates them.

    Prior IV harvested on previous runs is preserved by merging from the existing
    CSV before writing — without this, every indicators.py re-run would overwrite
    accumulated forward IV history with NaN.

    If today is a weekday and yfinance hasn't returned today's bar yet (end is
    exclusive), append a today-row with NaN OHLCV so the IV stamp lands on today's
    date instead of overwriting yesterday's close-of-day IV.

    Graceful: any failure leaves the affected columns NaN and prints a warning."""
    for col in IV_COLS:
        if col not in df.columns:
            df[col] = pd.NA

    # Merge prior IV from the existing CSV (preserve forward-accumulated history).
    if os.path.exists(csv_path):
        try:
            prior = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            # Preserve prior rows that fall outside the current df range — guards against
            # an accidental narrowed START_DATE wiping historical IV from the CSV.
            outside = prior.index.difference(df.index)
            if len(outside) > 0:
                print(f"  Preserving {len(outside)} prior rows outside current range "
                      f"({outside.min().date()} to {outside.max().date()})")
                df = pd.concat([df, prior.reindex(columns=df.columns).loc[outside]]).sort_index()
            common = df.index.intersection(prior.index)
            for col in IV_COLS:
                if col in prior.columns:
                    df.loc[common, col] = df.loc[common, col].combine_first(prior.loc[common, col])
        except Exception as e:
            print(f"  Could not merge prior IV from {csv_path}: {e}")

    # Add today-row if today is a weekday and not already in df. Holiday edge case
    # (e.g. Memorial Day) is accepted — the harvest still runs and stamps a row
    # that won't reconcile with a yfinance bar later.
    today = pd.Timestamp.today().normalize()
    if today.weekday() < 5 and today not in df.index:
        today_row = pd.DataFrame(index=[today], columns=df.columns)
        df = pd.concat([df, today_row]).sort_index()

    # Spot for ATM-strike anchor: latest non-NaN Close (skips today-row if just appended).
    spot_series = df["Close"].dropna()
    if spot_series.empty:
        print("  WARNING: No Close prices available — skipping IV harvest")
        return df
    spot = float(spot_series.iloc[-1])

    summary = get_chain_summary(ticker, spot)
    last_idx = df.index[-1]
    if summary is None:
        print(f"  WARNING: Massive chain unavailable — IV columns left NaN for {last_idx.date()}")
        return df

    for k in IV_COLS:
        df.loc[last_idx, k] = summary.get(k)

    skew_s = f"{summary['iv_skew_25d']:+.3f}" if summary["iv_skew_25d"] is not None else "n/a"
    term_s = f"{summary['term_structure']:.2f}" if summary["term_structure"] is not None else "n/a"
    pc_s   = f"{summary['put_call_oi_ratio']:.2f}" if summary["put_call_oi_ratio"] is not None else "n/a"
    print(f"  ATM IV (~{summary['atm_dte']}d): {summary['atm_iv_30d']:.1%} | "
          f"25Δ skew: {skew_s} | term: {term_s} | P/C OI: {pc_s}  → row {last_idx.date()}")
    return df


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    print("─" * 40)
    while True:
        try:
            ticker_in = input("  Ticker        [XYZ]: ").strip().upper()
            if ticker_in:
                break
            print("  Ticker cannot be empty.")
        except KeyboardInterrupt:
            print()
            sys.exit(0)
    start_in  = input(f"  Start date   [{START_DATE}]: ").strip()
    end_in    = input(f"  End date     [{END_DATE}]: ").strip()
    print("─" * 40)

    TICKER     = ticker_in
    START_DATE = start_in or START_DATE
    END_DATE   = end_in   or END_DATE

    try:
        df = fetch_data(TICKER, START_DATE, END_DATE)
    except Exception as e:
        print(f"  ERROR: Failed to fetch data for {TICKER} -> {e}")
        sys.exit(1)

    # Same-day close + gap backfill only applies to current-dated fetches —
    # a historical END_DATE must not get a today-row appended.
    if END_DATE == datetime.date.today().strftime("%Y-%m-%d"):
        df = augment_recent_prices_from_tradier(df, TICKER)

    df = add_indicators(df)
    print_signal_summary(df)
    plot_dashboard(df)

    csv_path = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")
    df = harvest_iv_snapshot(df, TICKER, csv_path)

    # Save full indicator table to CSV for Phase 2
    df["Ticker"] = TICKER
    df.to_csv(csv_path)
    print(f"Full indicator data saved -> {csv_path}")