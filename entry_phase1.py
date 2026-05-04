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

import datetime
import yfinance as yf
import pandas as pd
import ta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

# ─────────────────────────────────────────
# CONFIG — adjust these to your preference
# ─────────────────────────────────────────
TICKER       = "AMD"
START_DATE   = "2018-01-01"
END_DATE     = datetime.date.today().strftime("%Y-%m-%d")

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
    print(f"  Price:        ${latest['Close']:.2f}")
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

    # Set x-axis ticks to dates
    tick_spacing = max(1, len(plot_df) // 8)
    ax1.set_xticks(range(0, len(plot_df), tick_spacing))
    ax1.set_xticklabels(
        [plot_df.index[i].strftime("%b '%y") for i in range(0, len(plot_df), tick_spacing)],
        color="#8b949e", fontsize=7
    )
    ax1.set_xlim(-1, len(plot_df))
    ax1.set_ylabel("Price", **style)
    ax1.legend(fontsize=7, loc="upper left", facecolor="#161b22", labelcolor="white")
    ax1.tick_params(colors="#8b949e", labelbottom=False)
    ax1.spines[:].set_color("#30363d")

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
    ax5.set_xticks(range(0, len(plot_df), tick_spacing))
    ax5.set_xticklabels(
        [plot_df.index[i].strftime("%b '%y") for i in range(0, len(plot_df), tick_spacing)],
        rotation=30, ha="right", color="#8b949e", fontsize=7
    )

    plt.savefig(f"{TICKER.lower()}_dashboard.png", dpi=150, bbox_inches="tight",
                facecolor="#0d1117")
    print(f"Chart saved → {TICKER.lower()}_dashboard.png")
    plt.show()


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    print("─" * 40)
    ticker_in = input(f"  Ticker       [{TICKER}]: ").strip().upper()
    start_in  = input(f"  Start date   [{START_DATE}]: ").strip()
    end_in    = input(f"  End date     [{END_DATE}]: ").strip()
    print("─" * 40)

    TICKER     = ticker_in     or TICKER
    START_DATE = start_in      or START_DATE
    END_DATE   = end_in        or END_DATE

    df = fetch_data(TICKER, START_DATE, END_DATE)
    df = add_indicators(df)
    print_signal_summary(df)
    plot_dashboard(df)

    # Save full indicator table to CSV for Phase 2
    df["Ticker"] = TICKER
    df.to_csv(f"{TICKER.lower()}_indicators.csv")
    print(f"Full indicator data saved → {TICKER.lower()}_indicators.csv")