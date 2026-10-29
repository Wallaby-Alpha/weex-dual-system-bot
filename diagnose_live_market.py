"""
Live Market Diagnostics & Near-Miss Scanner for WEEX.
Inspects the current state of top altcoins to verify if the bot is actively evaluating setups,
shows the top momentum runners right now, and reports why setups have or haven't triggered.
"""

import sys
import time
import pandas as pd
import numpy as np

from config import config
from weex_client import WeexClient
from strategy_engine import StrategyEngine

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def run_diagnostics():
    print("\n" + "=" * 80)
    print("   WEEX LIVE MARKET SCANNER & PIPELINE DIAGNOSTICS")
    print("=" * 80)

    client = WeexClient(
        api_key=config.api_key,
        api_secret=config.api_secret,
        passphrase=config.passphrase,
        base_url=config.base_url
    )
    strategy = StrategyEngine(config)

    # 1. Check Exchange Info & Tickers
    print("\n[STEP 1] Fetching live 24h market tickers from WEEX...")
    tickers = client.get_24hr_tickers()
    if not tickers:
        print("  [ERROR] Unable to reach WEEX API. Check network connectivity.")
        return

    alts = [
        t for t in tickers 
        if t.get("symbol", "").endswith(config.quote_asset) 
        and t["symbol"] not in config.excluded_symbols
    ]
    alts.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
    universe = alts[:config.top_n_universe]
    print(f"  [+] Retrieved {len(tickers)} tickers. Scanning Top {len(universe)} volume altcoins.")
    print(f"      #1: {universe[0]['symbol']} (${float(universe[0]['quoteVolume']):,.0f}) | "
          f"#{len(universe)}: {universe[-1]['symbol']} (${float(universe[-1]['quoteVolume']):,.0f})")

    # 2. Scan every symbol in universe for recent momentum
    print(f"\n[STEP 2] Scanning latest 5m candlestick action across {len(universe)} symbols...")
    print(f"      Thresholds: Gain >= +{config.min_pump_gain_pct}%, Vol Spike >= {config.min_volume_spike_ratio}x, Turnover >= ${config.min_quote_vol_usdt:,.0f}")
    
    candidates = []
    active_triggers = []

    for idx, item in enumerate(universe):
        sym = item["symbol"]
        klines = client.get_klines(sym, interval="5m", limit=35)
        if len(klines) < 25:
            continue

        closes = [c["close"] for c in klines]
        highs = [c["high"] for c in klines]
        lows = [c["low"] for c in klines]
        opens = [c["open"] for c in klines]
        vols = [c["quote_volume"] for c in klines]

        # Calculate 20-period median volume
        median_vol = float(np.median(vols[-25:-5])) if len(vols) >= 25 else float(np.median(vols[:-2]))
        if median_vol <= 0:
            median_vol = 1.0

        # Find maximum surge in the last 15 candles
        n = len(klines)
        max_surge_gain = 0.0
        max_surge_vol_spike = 0.0
        max_surge_turnover = 0.0
        max_surge_time = ""
        is_pump = False

        for peak_idx in range(n - 12, n):
            peak_h = highs[peak_idx]
            peak_v = vols[peak_idx]
            for imp_len in range(1, 5):
                base_idx = peak_idx - imp_len
                if base_idx < 0:
                    continue
                base_o = opens[base_idx]
                gain = ((peak_h - base_o) / base_o) * 100.0
                spike = peak_v / median_vol
                if gain > max_surge_gain:
                    max_surge_gain = gain
                    max_surge_vol_spike = spike
                    max_surge_turnover = peak_v
                    max_surge_time = time.strftime('%H:%M UTC', time.gmtime(klines[peak_idx]['timestamp']/1000))

                if gain >= config.min_pump_gain_pct and spike >= config.min_volume_spike_ratio and peak_v >= config.min_quote_vol_usdt:
                    is_pump = True

        meta = client.get_exchange_info(sym) or {
            "contractVal": 1.0, "minOrderSize": 0.001, "pricePrecision": 2, "quantityPrecision": 2
        }

        # Check if currently triggering a trade
        trade_signal = strategy.scan_for_setups(sym, klines, meta)
        if trade_signal:
            active_triggers.append(trade_signal)

        candidates.append({
            "symbol": sym,
            "max_gain_pct": round(max_surge_gain, 2),
            "vol_spike": round(max_surge_vol_spike, 1),
            "turnover_usdt": round(max_surge_turnover, 0),
            "surge_time": max_surge_time,
            "is_pump": is_pump,
            "current_price": closes[-1]
        })
        time.sleep(0.04)

    # 3. Present Findings
    df_cand = pd.DataFrame(candidates)
    df_cand = df_cand.sort_values(by="max_gain_pct", ascending=False).reset_index(drop=True)

    print("\n" + "-" * 80)
    print("TOP 10 MOMENTUM ALTCOINS ON WEEX RIGHT NOW (LAST 60-90 MINS):")
    print("-" * 80)
    top10 = df_cand.head(10)
    for i, r in top10.iterrows():
        status_tag = "[QUALIFIED PUMP]" if r["is_pump"] else "[SUB-THRESHOLD]"
        print(f"  #{i+1:<2} {r['symbol']:<14} | Max Surge: +{r['max_gain_pct']:>5.2f}% | Vol Spike: {r['vol_spike']:>4.1f}x | Turnover: ${r['turnover_usdt']:>8,.0f} | Time: {r['surge_time']} | {status_tag}")

    print("\n" + "-" * 80)
    print("STATUS SUMMARY: WHY HAS/HASN'T A TRADE TRIGGERED?")
    print("-" * 80)

    pumps_found = df_cand[df_cand["is_pump"] == True]
    print(f"  * Total Active 5m Pumps in the last 60 mins: {len(pumps_found)}")
    print(f"  * Active Trade Triggers Ready to Fire: {len(active_triggers)}")

    if len(active_triggers) > 0:
        print("\n  [ALERT] Trade signal IS triggering right now!")
        for sig in active_triggers:
            print(f"    --> {sig['strategy']} on {sig['symbol']} | Entry: {sig['entry_price']} | SL: {sig['stop_loss']} | Qty: {sig['quantity']}")
    else:
        if len(pumps_found) == 0:
            top_runner = df_cand.iloc[0]
            print(f"\n  [OBSERVATION] The market is currently in a temporary lull.")
            print(f"    * Top runner was {top_runner['symbol']} with a max surge of +{top_runner['max_gain_pct']}% (Threshold: +{config.min_pump_gain_pct}%).")
            print(f"    * The bot is functioning correctly, but NO token has met the +{config.min_pump_gain_pct}% surge + {config.min_volume_spike_ratio}x volume threshold in the last ~1 hour.")
        else:
            print(f"\n  [OBSERVATION] Pump(s) were identified ({', '.join(pumps_found['symbol'].tolist())})!")
            print(f"    * However, their subsequent consolidation has not yet met the exact trigger:")
            print(f"      - System 1 requires price to enter the 38.2%-55% Fib zone with volume dropping < 55% AND a green reversal close.")
            print(f"      - System 2 requires price to break strictly above the peak high.")

    print("\n" + "=" * 80 + "\n")

if __name__ == "__main__":
    run_diagnostics()
