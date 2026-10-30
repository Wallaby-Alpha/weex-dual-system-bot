"""
Risk Management and Active Position Tracker.
Enforces 1R capital limits, concurrency controls, TP/SL monitoring, and time stops.
"""

import time
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger("weex_dual_bot.risk")

class RiskManager:
    def __init__(self, client, telegram, config):
        self.client = client
        self.telegram = telegram
        self.config = config
        self.active_trades: Dict[str, Dict[str, Any]] = {}
        self.closed_trades: List[Dict[str, Any]] = []
        self.closed_symbol_timestamps: Dict[str, float] = {} # Tracks exit time for cooldown
        self.total_realized_pnl: float = 0.0

    def can_open_new_trade(self, symbol: str) -> bool:
        if symbol in self.active_trades:
            return False
        if len(self.active_trades) >= self.config.max_open_positions:
            return False

        # Cooldown check: prevent re-entering same symbol too quickly
        last_exit = self.closed_symbol_timestamps.get(symbol, 0)
        cooldown_sec = self.config.symbol_cooldown_mins * 60
        if (time.time() - last_exit) < cooldown_sec:
            rem_mins = int((cooldown_sec - (time.time() - last_exit)) / 60)
            logger.debug(f"[*] {symbol} is in cooldown ({rem_mins}m remaining). Skipping.")
            return False

        return True

    def register_trade(self, trade_info: Dict[str, Any]) -> bool:
        symbol = trade_info["symbol"]
        trade_info["entry_timestamp"] = time.time()
        self.active_trades[symbol] = trade_info

        logger.info(f"[+] REGISTERED TRADE: {trade_info['strategy']} on {symbol} | Sized: {trade_info['quantity']} (1R=${trade_info['dollar_risk']:.2f})")
        
        # Send Telegram alert
        self.telegram.send_trade_entry(trade_info)
        return True

    def evaluate_open_positions(self):
        """
        Monitors active positions against current prices, TP, SL, and time stop.
        """
        if not self.active_trades:
            return

        symbols_to_close = []

        for symbol, trade in list(self.active_trades.items()):
            mark_p = self.client.get_mark_price(symbol)
            if not mark_p or mark_p <= 0:
                continue

            entry_p = trade["entry_price"]
            sl_p = trade["stop_loss"]
            tp_p = trade["take_profit"]
            qty = trade["quantity"]
            side = trade["side"]
            elapsed_mins = (time.time() - trade["entry_timestamp"]) / 60.0
            max_hold = trade.get("max_hold_mins", 60)

            exit_reason = None
            exit_price = mark_p

            # LONG evaluation
            if side == "LONG":
                if mark_p >= tp_p:
                    exit_reason = "TAKE_PROFIT"
                    exit_price = tp_p
                elif mark_p <= sl_p:
                    exit_reason = "STOP_LOSS"
                    exit_price = sl_p
                elif elapsed_mins >= max_hold:
                    exit_reason = "TIME_STOP"
                    exit_price = mark_p

            if exit_reason:
                symbols_to_close.append((symbol, trade, exit_reason, exit_price))

        for symbol, trade, reason, exit_p in symbols_to_close:
            self._close_position(symbol, trade, reason, exit_p)

    def _close_position(self, symbol: str, trade: Dict[str, Any], reason: str, exit_price: float):
        entry_p = trade["entry_price"]
        qty = trade["quantity"]
        dollar_risk = trade["dollar_risk"]

        # Calculate PnL in USD
        gross_ret = (exit_price - entry_p) / entry_p
        net_ret = gross_ret - 0.0012 # Account for 0.12% fees
        pnl_dollars = qty * (exit_price - entry_p)
        r_multiple = pnl_dollars / dollar_risk if dollar_risk > 0 else 0.0

        logger.info(f"[*] CLOSING POSITION: {symbol} [{reason}] @ {exit_price:.6g} | PnL: ${pnl_dollars:.2f} ({r_multiple:.2f}R)")

        # In Live Trading Mode, execute market close order on WEEX
        if not self.config.dry_run:
            try:
                self.client.close_market_position(
                    symbol=symbol,
                    side="SELL",
                    position_side="LONG",
                    quantity=qty
                )
            except Exception as e:
                logger.error(f"[!] Error sending market close to WEEX for {symbol}: {e}")

        # Update tracking
        self.total_realized_pnl += pnl_dollars
        trade["exit_reason"] = reason
        trade["exit_price"] = exit_price
        trade["exit_time"] = datetime.now(timezone.utc).isoformat()
        trade["pnl_dollars"] = round(pnl_dollars, 2)
        trade["r_multiple"] = round(r_multiple, 2)

        self.closed_trades.append(trade)
        self.closed_symbol_timestamps[symbol] = time.time()
        del self.active_trades[symbol]

        # Send Telegram exit alert
        self.telegram.send_trade_exit(
            trade=trade,
            exit_reason=reason,
            exit_price=exit_price,
            pnl_dollars=pnl_dollars,
            r_mult=r_multiple
        )
