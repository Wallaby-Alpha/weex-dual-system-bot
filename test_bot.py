"""
Local Verification and Diagnostics Script for WEEX Dual-System Bot.
Tests WEEX API connectivity, 1R=$1.00 USD position sizing math, and Telegram alert delivery.
"""

import sys
import time
from config import config
from weex_client import WeexClient
from strategy_engine import StrategyEngine
from telegram_notifier import TelegramNotifier

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def run_tests():
    print("\n" + "=" * 65)
    print("   RUNNING WEEX DUAL-BOT PRE-FLIGHT DIAGNOSTICS")
    print("=" * 65)

    client = WeexClient(
        api_key=config.api_key,
        api_secret=config.api_secret,
        passphrase=config.passphrase,
        base_url=config.base_url
    )
    strategy = StrategyEngine(config)
    telegram = TelegramNotifier(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        enabled=config.telegram_enabled
    )

    # 1. Test WEEX Public Market Connection
    print("\n[TEST 1] Testing WEEX Public REST Market Data...")
    try:
        tickers = client.get_24hr_tickers()
        print(f"  * Status: SUCCESS (Retrieved {len(tickers)} 24h ticker records)")
        sample_sym = "BTCUSDT" if any(t.get("symbol") == "BTCUSDT" for t in tickers) else tickers[0]["symbol"]
        
        meta = client.get_exchange_info(sample_sym)
        print(f"  * {sample_sym} Metadata: minOrderSize={meta.get('minOrderSize')}, contractVal={meta.get('contractVal')}, pricePrec={meta.get('pricePrecision')}, qtyPrec={meta.get('quantityPrecision')}")
        
        klines = client.get_klines(sample_sym, interval="5m", limit=10)
        print(f"  * 5m Klines Fetch: SUCCESS ({len(klines)} bars retrieved, latest close: ${klines[-1]['close']:,.2f})")
    except Exception as e:
        print(f"  * Status: FAILED ({e})")
        return

    # 2. Test 1R = $1.00 USD Risk Sizing Formula
    print("\n[TEST 2] Testing Exact 1R = $1.00 USD Position Sizing Math...")
    test_cases = [
        {"symbol": "SOLUSDT", "entry": 100.0, "sl": 96.0, "meta": {"contractVal": 1.0, "minOrderSize": 0.01, "quantityPrecision": 2}},
        {"symbol": "DOGEUSDT", "entry": 0.20, "sl": 0.19, "meta": {"contractVal": 1.0, "minOrderSize": 1.0, "quantityPrecision": 0}},
        {"symbol": "BTCUSDT", "entry": 80000.0, "sl": 78000.0, "meta": {"contractVal": 0.0001, "minOrderSize": 0.0001, "quantityPrecision": 4}},
    ]

    for tc in test_cases:
        qty, r_dist, r_pct = strategy.calculate_1r_position_size(
            symbol_meta=tc["meta"],
            entry_price=tc["entry"],
            stop_loss_price=tc["sl"],
            dollar_risk=1.00
        )
        c_val = tc["meta"].get("contractVal", 1.0)
        actual_loss = qty * r_dist * c_val
        print(f"  * {tc['symbol']}: Entry=${tc['entry']}, SL=${tc['sl']} (Risk: {r_pct:.2f}%)")
        print(f"    --> Sized Qty: {qty} contracts | Total Sized Risk: ${actual_loss:.2f} USD (Target: $1.00)")

    # 3. Test Private API Credentials (if provided)
    print("\n[TEST 3] Testing Private WEEX Account Credentials...")
    if config.api_key and config.api_secret and config.passphrase:
        try:
            balance = client.get_available_margin()
            print(f"  * Status: AUTHENTICATED! Available USDT Balance: ${balance:,.2f}")
        except Exception as e:
            print(f"  * Status: AUTHENTICATION ERROR ({e})")
    else:
        print("  * Status: SKIPPED (API keys not set in .env. Bot will run in DRY_RUN mode).")

    # 4. Test Telegram Bot Notification (if provided)
    print("\n[TEST 4] Testing Telegram Bot Notification Delivery...")
    if telegram.enabled:
        test_msg = (
            "🤖 <b>WEEX BOT PRE-FLIGHT TEST ALERT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• <b>Status</b>: ✅ Operational\n"
            "• <b>Risk Unit</b>: <code>1R = $1.00 USD</code>\n"
            "• <b>Message</b>: <i>Diagnostics check completed successfully!</i>"
        )
        sent = telegram.send_message(test_msg)
        if sent:
            print("  * Status: SUCCESS (Test message delivered to Telegram!)")
        else:
            print("  * Status: FAILED (Check BOT_TOKEN and CHAT_ID in .env)")
    else:
        print("  * Status: DISABLED (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured in .env).")

    print("\n" + "=" * 65)
    print("   PRE-FLIGHT DIAGNOSTICS COMPLETE")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    run_tests()
