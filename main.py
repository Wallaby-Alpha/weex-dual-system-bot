"""
Master Execution Daemon for the WEEX Dual-System Trading Bot.
Polls 5m candlestick data, detects pumps, sizes at 1R = $1.00 USD, and routes trades & alerts.
"""

import time
import signal
import sys
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from config import config
from weex_client import WeexClient
from telegram_notifier import TelegramNotifier
from strategy_engine import StrategyEngine
from risk_manager import RiskManager

logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("weex_dual_bot.main")

class WeexDualBotDaemon:
    def __init__(self):
        self.config = config
        self.client = WeexClient(
            api_key=config.api_key,
            api_secret=config.api_secret,
            passphrase=config.passphrase,
            base_url=config.base_url
        )
        self.telegram = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
            enabled=config.telegram_enabled
        )
        self.strategy = StrategyEngine(config)
        self.risk_manager = RiskManager(self.client, self.telegram, config)
        self.running = True
        self.universe_symbols: List[str] = []
        self.last_universe_refresh = 0
        self.last_heartbeat_time = time.time()

        # Handle systemd / docker signals
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        logger.info("[*] Shutdown signal received. Exiting daemon gracefully...")
        self.running = False

    def initialize(self) -> bool:
        logger.info("=" * 65)
        logger.info("   WEEX DUAL-SYSTEM MOMENTUM TRADING BOT INITIALIZED")
        logger.info(f"   Mode: {'🟡 DRY RUN (Paper Trading)' if self.config.dry_run else '🟢 LIVE TRADING'}")
        logger.info(f"   Risk Unit (1R): ${self.config.dollar_risk_per_trade:.2f} USD")
        logger.info(f"   Max Open Positions: {self.config.max_open_positions}")
        logger.info(f"   Telegram Alerts: {'ENABLED' if self.telegram.enabled else 'DISABLED'}")
        logger.info("=" * 65)

        # 1. Fetch Universe of Top Volume Altcoins
        self._refresh_universe()
        if not self.universe_symbols:
            logger.error("[!] Failed to load WEEX altcoin universe. Halting.")
            return False

        # 2. Check WEEX Account Balance
        balance = 1000.0 # Default for dry-run
        if not self.config.dry_run:
            try:
                balance = self.client.get_available_margin()
                logger.info(f"[+] Connected to live WEEX account! Available Balance: ${balance:,.2f} USDT")
                if balance < self.config.dollar_risk_per_trade:
                    logger.warning(f"[!] Balance (${balance:.2f}) is lower than 1R risk (${self.config.dollar_risk_per_trade:.2f})!")
            except Exception as e:
                logger.error(f"[!] WEEX account authentication failed: {e}")
                return False

        # 3. Send Startup Banner to Telegram
        self.telegram.send_startup_banner(
            dry_run=self.config.dry_run,
            dollar_risk=self.config.dollar_risk_per_trade,
            universe_count=len(self.universe_symbols),
            balance=balance
        )
        return True

    def _refresh_universe(self):
        logger.info("[*] Discovering top volume altcoins on WEEX...")
        tickers = self.client.get_24hr_tickers()
        if not tickers:
            return

        alts = [
            t for t in tickers 
            if t.get("symbol", "").endswith(self.config.quote_asset) 
            and t["symbol"] not in self.config.excluded_symbols
        ]
        alts.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        self.universe_symbols = [a["symbol"] for a in alts[:self.config.top_n_universe]]
        self.last_universe_refresh = time.time()
        logger.info(f"[+] Loaded Top {len(self.universe_symbols)} volume altcoin contracts on WEEX.")

    def run(self):
        if not self.initialize():
            return

        logger.info("[*] Daemon listening for 5m momentum setups...")
        
        while self.running:
            try:
                loop_start = time.time()

                # 1. Refresh universe hourly
                if time.time() - self.last_universe_refresh > 3600:
                    self._refresh_universe()

                # 2. Monitor active positions (check TP, SL, Time Stops)
                self.risk_manager.evaluate_open_positions()

                # 3. Scan universe if we have capacity for new trades
                top_momentum = {"symbol": "None", "gain": 0.0, "spike": 0.0}
                pumps_detected = 0

                if len(self.risk_manager.active_trades) < self.config.max_open_positions:
                    for symbol in self.universe_symbols:
                        if not self.running:
                            break
                        if not self.risk_manager.can_open_new_trade(symbol):
                            continue

                        # Fetch recent 5m klines
                        klines = self.client.get_klines(symbol, interval="5m", limit=45)
                        if len(klines) < 35:
                            continue

                        # Check recent impulse for observability
                        recent_h = max(c["high"] for c in klines[-4:])
                        prior_o = klines[-4]["open"]
                        if prior_o > 0:
                            g = ((recent_h - prior_o) / prior_o) * 100.0
                            if g > top_momentum["gain"]:
                                top_momentum = {"symbol": symbol, "gain": round(g, 1), "spike": 1.0}

                        # Fetch symbol precision specifications
                        meta = self.client.get_exchange_info(symbol)
                        if not meta:
                            continue

                        # Evaluate Dual Strategy rules
                        signal = self.strategy.scan_for_setups(symbol, klines, meta)
                        if signal:
                            pumps_detected += 1
                            self._execute_trade_signal(signal, meta)

                        time.sleep(0.02) # Gentle rate-limit pacing (scans 400 coins in ~18s)

                    logger.info(f"[SCAN COMPLETED] {len(self.universe_symbols)} pairs checked | Active Triggers: {pumps_detected} | Highest 15m Surge: {top_momentum['symbol']} (+{top_momentum['gain']}%)")

                # 4. Hourly Heartbeat to Telegram
                if time.time() - self.last_heartbeat_time > 3600:
                    bal = self.client.get_available_margin() if not self.config.dry_run else 1000.0
                    self.telegram.send_heartbeat(
                        active_count=len(self.risk_manager.active_trades),
                        balance=bal,
                        daily_pnl=self.risk_manager.total_realized_pnl,
                        total_trades=len(self.risk_manager.closed_trades)
                    )
                    self.last_heartbeat_time = time.time()

                # Pacing sleep
                elapsed = time.time() - loop_start
                sleep_time = max(2.0, self.config.scan_interval_sec - elapsed)
                time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"[!] Error in main daemon loop: {e}", exc_info=True)
                time.sleep(5)

        logger.info("[*] Bot loop terminated.")

    def _execute_trade_signal(self, signal: Dict[str, Any], meta: Dict[str, Any]):
        symbol = signal["symbol"]
        qty = signal["quantity"]
        entry_p = signal["entry_price"]
        sl_p = signal["stop_loss"]
        tp_p = signal["take_profit"]

        logger.info(f"[TRIGGER] {signal['strategy']} on {symbol} -> Entry: {entry_p}, SL: {sl_p}, TP: {tp_p}, Qty: {qty} (1R=${signal['dollar_risk']:.2f})")

        # In Live Trading Mode:
        if not self.config.dry_run:
            try:
                # 1. Set dynamically calculated safe leverage (Anti-Liquidation Protection)
                lev = signal.get("leverage", self.config.default_leverage)
                self.client.set_leverage(symbol, lev)
                logger.info(f"[RISK GUARD] {symbol} leverage dynamically set to {lev}x (Liquidation buffered beyond SL)")

                # 2. Submit market buy entry order
                res = self.client.place_market_order(
                    symbol=symbol,
                    side="BUY",
                    position_side="LONG",
                    quantity=qty
                )
                if not res.get("success"):
                    logger.error(f"[!] Failed to execute live order for {symbol}: {res.get('error')}")
                    return

                # 3. Submit native exchange-level TP/SL plan orders
                sl_ok = self.client.place_native_tpsl_plan_order(symbol, "STOP_LOSS", sl_p, position_side="LONG")
                tp_ok = self.client.place_native_tpsl_plan_order(symbol, "TAKE_PROFIT", tp_p, position_side="LONG")
                
                if sl_ok:
                    logger.info(f"[+] Exchange-level STOP_LOSS order active on WEEX @ {sl_p}")
                else:
                    logger.warning(f"[!] Warning: WEEX rejected native STOP_LOSS order for {symbol}. Bot software monitor will act as fallback.")

                if tp_ok:
                    logger.info(f"[+] Exchange-level TAKE_PROFIT order active on WEEX @ {tp_p}")
                else:
                    logger.warning(f"[!] Warning: WEEX rejected native TAKE_PROFIT order for {symbol}.")

            except Exception as e:
                logger.error(f"[!] Live order submission failed for {symbol}: {e}")
                return

        # Register with Risk Manager (handles alerts and position tracking)
        self.risk_manager.register_trade(signal)

if __name__ == "__main__":
    bot = WeexDualBotDaemon()
    bot.run()
