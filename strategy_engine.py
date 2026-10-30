"""
Strategy Detection and Risk-Sizing Engine.
Implements:
  - System 1: Pump FIB50 Reversal + Dynamic ATR (71.4% WR, 4.64 PF)
  - System 2: Pump Confirmed Breakout + Tight Structure (53.6% WR, 1.32 PF)
  - System 3: Crash Capitulation Reversal (82.4% WR, 6.55 PF - Buying 5m Dumps)
All systems maintain exact 1R = $1.00 USD risk sizing.
"""

import math
import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, Tuple, List

from config import config

logger = logging.getLogger("weex_dual_bot.strategy")

class StrategyEngine:
    def __init__(self, bot_config=None):
        self.config = bot_config or config

    def calculate_atr(self, candles: List[Dict[str, Any]], period: int = 14) -> float:
        if len(candles) < period + 1:
            return 0.0
        highs = np.array([c["high"] for c in candles], dtype=np.float64)
        lows = np.array([c["low"] for c in candles], dtype=np.float64)
        closes = np.array([c["close"] for c in candles], dtype=np.float64)

        tr = np.maximum(highs[1:] - lows[1:], np.maximum(abs(highs[1:] - closes[:-1]), abs(lows[1:] - closes[:-1])))
        if len(tr) < period:
            return float(np.mean(tr)) if len(tr) > 0 else 0.0
        return float(np.mean(tr[-period:]))

    def calculate_1r_position_size(
        self,
        symbol_meta: Dict[str, Any],
        entry_price: float,
        stop_loss_price: float,
        dollar_risk: float = 1.00
    ) -> Tuple[float, float, float]:
        """
        Calculates exact contract quantity to risk exactly $1.00 USD.
        Returns: (sized_quantity, risk_distance, risk_percent)
        """
        risk_dist = abs(entry_price - stop_loss_price)
        if risk_dist <= 0 or entry_price <= 0:
            return 0.0, 0.0, 0.0

        risk_pct = (risk_dist / entry_price) * 100.0

        # Contract value multiplier (usually 1.0 on USDT-margined perps, or 0.001 on meme coins)
        contract_val = float(symbol_meta.get("contractVal", 1.0))
        if contract_val <= 0:
            contract_val = 1.0

        # Quantity = $1.00 / (risk_distance * contract_val)
        raw_qty = dollar_risk / (risk_dist * contract_val)

        min_size = float(symbol_meta.get("minOrderSize", 0.0001))
        qty_prec = int(symbol_meta.get("quantityPrecision", 2))

        # Precision round
        sized_qty = max(min_size, round(raw_qty, qty_prec))
        if qty_prec == 0:
            sized_qty = max(min_size, math.floor(raw_qty))

        return sized_qty, risk_dist, risk_pct

    def calculate_safe_leverage(
        self,
        entry_price: float,
        stop_loss_price: float,
        safety_multiplier: float = 1.6
    ) -> int:
        """
        Dynamically calculates safe leverage to GUARANTEE that the Stop Loss
        is ALWAYS reached before the liquidation price.
        Enforces: Liquidation Distance >= 1.6x Stop Loss Distance.
        """
        risk_pct = abs(entry_price - stop_loss_price) / entry_price
        if risk_pct <= 0:
            return 1

        # On WEEX, liquidation distance approx: (0.90 / Leverage)
        # We require (0.90 / Leverage) >= Risk_Pct * safety_multiplier
        max_safe_lev = int(math.floor(0.90 / (risk_pct * safety_multiplier)))
        return max(1, min(self.config.default_leverage, max_safe_lev))

    def scan_for_setups(
        self,
        symbol: str,
        candles: List[Dict[str, Any]],
        symbol_meta: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Analyzes 5m candles and checks for active System 1, 2, or 3 triggers.
        """
        if len(candles) < 35:
            return None

        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        opens = [c["open"] for c in candles]
        vols = [c["quote_volume"] for c in candles]

        n = len(candles)
        curr_idx = n - 1
        curr_c = closes[curr_idx]
        curr_o = opens[curr_idx]
        curr_h = highs[curr_idx]
        curr_l = lows[curr_idx]
        curr_v = vols[curr_idx]

        # Rolling 20-period median volume
        median_vol = float(np.median(vols[-25:-5])) if len(vols) >= 25 else float(np.median(vols[:-2]))
        if median_vol <= 0:
            median_vol = 1.0

        # ATR-14 for dynamic risk sizing
        atr14 = self.calculate_atr(candles, period=14)
        if atr14 <= 0:
            atr14 = curr_c * 0.015

        # =========================================================================
        # PUMP DETECTION (FOR SYSTEM 1 & SYSTEM 2)
        # =========================================================================
        pump_candidate = None
        for peak_idx in range(n - 12, n - 1):
            if peak_idx < 10:
                continue

            peak_h = highs[peak_idx]
            peak_v = vols[peak_idx]

            for imp_len in range(1, 5):
                base_idx = peak_idx - imp_len
                if base_idx < 0:
                    continue
                base_o = opens[base_idx]
                if base_o <= 0:
                    continue

                gain_pct = ((peak_h - base_o) / base_o) * 100.0
                vol_ratio = peak_v / median_vol

                if gain_pct >= self.config.min_pump_gain_pct and vol_ratio >= self.config.min_volume_spike_ratio and peak_v >= self.config.min_quote_vol_usdt:
                    prior_h = max(highs[max(0, base_idx - 20) : base_idx]) if base_idx > 0 else 0
                    if peak_h > prior_h:
                        pump_candidate = {
                            "base_idx": base_idx,
                            "peak_idx": peak_idx,
                            "base_price": base_o,
                            "peak_price": peak_h,
                            "gain_pct": gain_pct,
                            "peak_vol": peak_v,
                            "vol_spike": vol_ratio
                        }
                        break
            if pump_candidate:
                break

        # Check System 1 & 2 if pump candidate found
        if pump_candidate:
            peak_p = pump_candidate["peak_price"]
            base_p = pump_candidate["base_price"]
            imp_range = peak_p - base_p
            p_idx = pump_candidate["peak_idx"]

            # System 1: FIB50_REVERSAL + DYNAMIC_ATR (71.4% Win Rate, 4.64 PF)
            if self.config.sys1_enabled:
                fib_382 = peak_p - 0.382 * imp_range
                fib_618 = peak_p - 0.618 * imp_range
                post_lows = lows[p_idx + 1 : curr_idx + 1]

                if len(post_lows) > 0 and min(post_lows) <= fib_382 and min(post_lows) >= fib_618:
                    if curr_c > curr_o and curr_v < (0.55 * pump_candidate["peak_vol"]):
                        stop_loss = curr_c - (self.config.sys1_atr_multiplier * atr14)
                        risk_dist = curr_c - stop_loss

                        if risk_dist > (curr_c * 0.003):
                            take_profit = curr_c + (self.config.sys1_reward_risk_ratio * risk_dist)
                            qty, r_dist, r_pct = self.calculate_1r_position_size(
                                symbol_meta, curr_c, stop_loss, self.config.dollar_risk_per_trade
                            )
                            safe_lev = self.calculate_safe_leverage(curr_c, stop_loss)
                            if qty > 0:
                                return {
                                    "strategy": "System 1: FIB50 Reversal + Dynamic ATR",
                                    "symbol": symbol,
                                    "side": "LONG",
                                    "entry_price": curr_c,
                                    "stop_loss": stop_loss,
                                    "take_profit": take_profit,
                                    "quantity": qty,
                                    "dollar_risk": self.config.dollar_risk_per_trade,
                                    "risk_pct": r_pct,
                                    "leverage": safe_lev,
                                    "target_r": self.config.sys1_reward_risk_ratio,
                                    "max_hold_mins": self.config.sys1_max_hold_mins,
                                    "impulse_meta": pump_candidate
                                }

            # System 2: CONFIRMED_BREAKOUT + TIGHT_STRUCTURE (53.6% Win Rate, 1.32 PF)
            if self.config.sys2_enabled:
                fib_618 = peak_p - 0.618 * imp_range
                post_lows = lows[p_idx + 1 : curr_idx + 1]
                cons_low = min(post_lows) if len(post_lows) > 0 else curr_l

                if cons_low >= fib_618:
                    if curr_h > peak_p and closes[curr_idx - 1] <= peak_p:
                        entry_p = max(curr_c, peak_p * 1.001)
                        stop_loss = min(cons_low * 0.998, entry_p * 0.975)
                        risk_dist = entry_p - stop_loss

                        if risk_dist > (entry_p * 0.003):
                            take_profit = entry_p + (self.config.sys2_tp1_ratio * risk_dist)
                            qty, r_dist, r_pct = self.calculate_1r_position_size(
                                symbol_meta, entry_p, stop_loss, self.config.dollar_risk_per_trade
                            )
                            safe_lev = self.calculate_safe_leverage(entry_p, stop_loss)
                            if qty > 0:
                                return {
                                    "strategy": "System 2: Confirmed Breakout + Tight Structure",
                                    "symbol": symbol,
                                    "side": "LONG",
                                    "entry_price": entry_p,
                                    "stop_loss": stop_loss,
                                    "take_profit": take_profit,
                                    "quantity": qty,
                                    "dollar_risk": self.config.dollar_risk_per_trade,
                                    "risk_pct": r_pct,
                                    "leverage": safe_lev,
                                    "target_r": self.config.sys2_tp1_ratio,
                                    "max_hold_mins": self.config.sys2_max_hold_mins,
                                    "impulse_meta": pump_candidate
                                }

        # =========================================================================
        # CRASH DETECTION (FOR SYSTEM 3: CAPITULATION BOUNCE REVERSAL)
        # =========================================================================
        if self.config.sys3_enabled:
            crash_candidate = None
            for trough_idx in range(n - 8, n - 1):
                if trough_idx < 10:
                    continue

                trough_l = lows[trough_idx]
                trough_v = vols[trough_idx]

                for imp_len in range(1, 5):
                    base_idx = trough_idx - imp_len
                    if base_idx < 0:
                        continue
                    base_h = highs[base_idx]
                    if base_h <= 0:
                        continue

                    drop_pct = ((base_h - trough_l) / base_h) * 100.0
                    vol_ratio = trough_v / median_vol

                    # Anti-Illiquid Guard:
                    # 1. Crash candle must have at least $50,000 turnover
                    # 2. Baseline volume must be >= $10,000 (filters illiquid ghost books like BLESS)
                    if (drop_pct >= self.config.min_crash_drop_pct and 
                        vol_ratio >= self.config.min_volume_spike_ratio and 
                        trough_v >= self.config.min_crash_quote_vol_usdt and
                        median_vol >= 10000.0):
                        # Must break 20-period prior low
                        prior_l = min(lows[max(0, base_idx - 20) : base_idx]) if base_idx > 0 else trough_l
                        if trough_l < prior_l:
                            crash_candidate = {
                                "base_idx": base_idx,
                                "trough_idx": trough_idx,
                                "base_price": base_h,
                                "trough_price": trough_l,
                                "drop_pct": drop_pct,
                                "trough_vol": trough_v,
                                "vol_spike": vol_ratio
                            }
                            break
                if crash_candidate:
                    break

            if crash_candidate:
                trough_p = crash_candidate["trough_price"]
                base_p = crash_candidate["base_price"]
                drop_range = base_p - trough_p
                t_idx = crash_candidate["trough_idx"]

                # Ensure current candle is within 6 bars of trough
                if (curr_idx - t_idx) <= 6 and (curr_idx > t_idx):
                    # Check Reversal Trigger (First Green Candle, Bullish Engulfing, or Pin Bar)
                    rng = curr_h - curr_l if (curr_h - curr_l) > 0 else 1e-6
                    lower_wick = min(curr_o, curr_c) - curr_l
                    is_pin_bar = (lower_wick / rng >= 0.40) and (curr_c >= (curr_l + 0.5 * rng))
                    is_green_bar = curr_c > curr_o
                    prev_h = highs[curr_idx - 1]
                    is_engulfing = is_green_bar and curr_c > prev_h

                    if is_green_bar or is_pin_bar or is_engulfing:
                        # Stop loss: 1.5x ATR-14 below entry or 0.5% below trough
                        stop_loss = min(curr_c - (self.config.sys3_atr_multiplier * atr14), trough_p * 0.995)
                        risk_dist = curr_c - stop_loss

                        if risk_dist > (curr_c * 0.003):
                            # Target: Fib 38.2% retracement of the crash drop
                            fib382_target = trough_p + (self.config.sys3_target_fib * drop_range)
                            take_profit = max(fib382_target, curr_c + (1.2 * risk_dist))
                            target_r = round((take_profit - curr_c) / risk_dist, 2)

                            qty, r_dist, r_pct = self.calculate_1r_position_size(
                                symbol_meta, curr_c, stop_loss, self.config.dollar_risk_per_trade
                            )

                            safe_lev = self.calculate_safe_leverage(curr_c, stop_loss)
                            if qty > 0:
                                return {
                                    "strategy": "System 3: Capitulation Bounce Reversal",
                                    "symbol": symbol,
                                    "side": "LONG",
                                    "entry_price": curr_c,
                                    "stop_loss": stop_loss,
                                    "take_profit": take_profit,
                                    "quantity": qty,
                                    "dollar_risk": self.config.dollar_risk_per_trade,
                                    "risk_pct": r_pct,
                                    "leverage": safe_lev,
                                    "target_r": target_r,
                                    "max_hold_mins": self.config.sys3_max_hold_mins,
                                    "impulse_meta": crash_candidate
                                }

        return None
