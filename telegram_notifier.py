"""
Telegram Notification Engine for WEEX Trading Bot.
Delivers real-time trade execution alerts, pump discoveries, and risk updates.
"""

import time
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger("weex_dual_bot.telegram")

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled and bool(bot_token and chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        if self.enabled:
            logger.info("[+] Telegram alerts ENABLED.")
        else:
            logger.info("[-] Telegram alerts DISABLED (Missing BOT_TOKEN or CHAT_ID).")

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Sends formatted alert message to configured Telegram channel/group.
        """
        if not self.enabled:
            return False

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }

        try:
            resp = requests.post(self.base_url, json=payload, timeout=8)
            if resp.status_code == 200:
                return True
            else:
                logger.warning(f"Telegram API response [{resp.status_code}]: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to deliver Telegram message: {e}")
            return False

    def send_startup_banner(self, dry_run: bool, dollar_risk: float, universe_count: int, balance: float):
        mode_str = "🟡 <b>DRY RUN (Paper Trading)</b>" if dry_run else "🟢 <b>LIVE EXECUTION</b>"
        msg = (
            f"🚀 <b>WEEX TRI-SYSTEM BOT ACTIVATED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Status</b>: {mode_str}\n"
            f"• <b>Risk Unit (1R)</b>: <code>${dollar_risk:.2f} USD</code>\n"
            f"• <b>Available USDT</b>: <code>${balance:,.2f}</code>\n"
            f"• <b>Scanned Universe</b>: <code>{universe_count} Altcoins</code>\n"
            f"• <b>Active Systems</b>:\n"
            f"  1. <i>Pump FIB50 Reversal</i> (71.4% WR, 4.64 PF)\n"
            f"  2. <i>Pump Confirmed Breakout</i> (53.6% WR, 1.32 PF)\n"
            f"  3. <i>Crash Capitulation Reversal</i> (82.4% WR, 6.55 PF)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ <i>Scanning WEEX 5m klines every 30s...</i>"
        )
        self.send_message(msg)

    def send_pump_detected(self, symbol: str, gain_pct: float, vol_spike: float, turnover: float):
        msg = (
            f"⚡ <b>5M PUMP DETECTED: {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Impulse Surge</b>: <code>+{gain_pct:.1f}%</code> in ≤ 20 mins\n"
            f"• <b>Volume Spike</b>: <code>{vol_spike:.1f}x</code> baseline\n"
            f"• <b>Candle Turnover</b>: <code>${turnover:,.0f} USDT</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 <i>Monitoring consolidation for System 1 or System 2 trigger...</i>"
        )
        self.send_message(msg)

    def send_crash_detected(self, symbol: str, drop_pct: float, vol_spike: float, turnover: float):
        msg = (
            f"💥 <b>5M CRASH DETECTED: {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Impulse Drop</b>: <code>-{drop_pct:.1f}%</code> in ≤ 20 mins\n"
            f"• <b>Volume Spike</b>: <code>{vol_spike:.1f}x</code> baseline\n"
            f"• <b>Candle Turnover</b>: <code>${turnover:,.0f} USDT</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <i>Monitoring trough for System 3 Capitulation Reversal trigger...</i>"
        )
        self.send_message(msg)

    def send_trade_entry(self, trade: Dict[str, Any]):
        sys_name = trade.get("strategy", "System")
        sym = trade.get("symbol", "")
        side = trade.get("side", "LONG")
        entry_p = trade.get("entry_price", 0.0)
        sl_p = trade.get("stop_loss", 0.0)
        tp_p = trade.get("take_profit", 0.0)
        qty = trade.get("quantity", 0.0)
        r_risk = trade.get("dollar_risk", 1.00)
        risk_pct = trade.get("risk_pct", 0.0)
        target_r = trade.get("target_r", 1.5)

        msg = (
            f"🟢 <b>TRADE OPENED: {sym} ({side})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>System</b>: <code>{sys_name}</code>\n"
            f"• <b>Entry Price</b>: <code>{entry_p:.6g}</code>\n"
            f"• <b>Sized Qty</b>: <code>{qty} {sym}</code>\n"
            f"• <b>Stop Loss</b>: <code>{sl_p:.6g} (-{risk_pct:.2f}%)</code>\n"
            f"• <b>Take Profit</b>: <code>{tp_p:.6g} (+{risk_pct * target_r:.2f}%)</code>\n"
            f"• <b>Position Risk (1R)</b>: <code>${r_risk:.2f} USD</code>\n"
            f"• <b>Target R:R</b>: <code>{target_r}:1</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <i>Native exchange TP/SL plan orders submitted.</i>"
        )
        self.send_message(msg)

    def send_trade_exit(self, trade: Dict[str, Any], exit_reason: str, exit_price: float, pnl_dollars: float, r_mult: float):
        sym = trade.get("symbol", "")
        entry_p = trade.get("entry_price", 0.0)
        is_win = pnl_dollars > 0
        icon = "🎯" if is_win else "🛑"
        color_tag = "PROFIT" if is_win else "LOSS"

        msg = (
            f"{icon} <b>POSITION CLOSED: {sym} [{color_tag}]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Exit Reason</b>: <code>{exit_reason}</code>\n"
            f"• <b>Entry Price</b>: <code>{entry_p:.6g}</code>\n"
            f"• <b>Exit Price</b>: <code>{exit_price:.6g}</code>\n"
            f"• <b>Net Realized PnL</b>: <code>{'+' if is_win else ''}${pnl_dollars:.2f} USD</code>\n"
            f"• <b>Outcome</b>: <code>{'+' if is_win else ''}{r_mult:.2f}R</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 <i>Risk allocation capital freed for new setups.</i>"
        )
        self.send_message(msg)

    def send_heartbeat(self, active_count: int, balance: float, daily_pnl: float, total_trades: int):
        msg = (
            f"💓 <b>WEEX BOT HEARTBEAT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Active Trades</b>: <code>{active_count} open</code>\n"
            f"• <b>Current USDT</b>: <code>${balance:,.2f}</code>\n"
            f"• <b>Session PnL</b>: <code>{'+' if daily_pnl >= 0 else ''}${daily_pnl:.2f} USD</code>\n"
            f"• <b>Total Trades Today</b>: <code>{total_trades}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <i>Engine running smoothly on DigitalOcean droplet.</i>"
        )
        self.send_message(msg)
