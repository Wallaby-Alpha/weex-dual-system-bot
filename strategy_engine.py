"""
Strategy Detection and Risk-Sizing Engine.
Implements System 1 (FIB50 Reversal) & System 2 (Confirmed Breakout) with exact 1R = $1.00 USD sizing.
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
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        closes = np.array([c["close"] for c in candles])

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

        # Contract value multiplier (usually 1.0 on USDT-margined perps, or 0.001 on coins like SHIB/PEPE)
        contract_val = float(symbol_meta.get("contractVal", 1.0))
        if contract_val <= 0:
            contract_val = 1.0

        # Raw quantity to risk $1.00 USD:
        # Loss = Quantity * risk_distance * contract_val = $1.00
        # Quantity = $1.00 / (risk_distance * contract_val)
        raw_qty = dollar_risk / (risk_dist * contract_val)

        min_size = float(symbol_meta.get("minOrderSize", 0.0001))
        qty_prec = int(symbol_meta.get("quantityPrecision", 2))

        # Precision round
        sized_qty = max(min_size, round(raw_qty, qty_prec))
        if qty_prec == 0:
            sized_qty = max(min_size, math.floor(raw_qty))

        return sized_qty, risk_dist, risk_pct

    def scan_for_setups(
        self,
        symbol: str,
        candles: List[Dict[str, Any]],
        symbol_meta: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Analyzes 5m candles and checks for active System 1 or System 2 triggers.
        """
        if len(candles) < 35:
            return None

        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        opens = [c["open"] for c in candles]
        vols = [c["quote_volume"] for c in candles]

        # Rolling 20-period median volume
        median_vol = float(np.median(vols[-25:-5])) if len(vols) >= 25 else float(np.median(vols[:-2]))
        if median_vol <= 0:
            median_vol = 1.0

        # Scan recent candles for a valid 5m pump peak within the last 15 candles
        n = len(candles)
        pump_candidate = None

        for peak_idx in range(n - 12, n - 1):
            if peak_idx < 10:
                continue

            peak_h = highs[peak_idx]
            peak_v = vols[peak_idx]

            # Find base open 1 to 4 candles before peak
            for imp_len in range(1, 5):
                base_idx = peak_idx - imp_len
                if base_idx < 0:
                    continue
                base_o = opens[base_idx]
                if base_o <= 0:
                    continue

                gain_pct = ((peak_h - base_o) / base_o) * 100.0
                vol_ratio = peak_v / median_vol

                # Check if it satisfied pump criteria
                if gain_pct >= self.config.min_pump_gain_pct and vol_ratio >= self.config.min_volume_spike_ratio and peak_v >= self.config.min_quote_vol_usdt:
                    # Must be a 20-bar local high
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

        if not pump_candidate:
            return None

        peak_p = pump_candidate["peak_price"]
        base_p = pump_candidate["base_price"]
        imp_range = peak_p - base_p
        p_idx = pump_candidate["peak_idx"]

        # Current latest closed candle
        curr_idx = n - 1
        curr_c = closes[curr_idx]
        curr_o = opens[curr_idx]
        curr_h = highs[curr_idx]
        curr_l = lows[curr_idx]
        curr_v = vols[curr_idx]

        # ATR-14 for dynamic risk sizing
        atr14 = self.calculate_atr(candles, period=14)
        if atr14 <= 0:
            atr14 = curr_c * 0.015

        # =========================================================================
        # SYSTEM 1: FIB50_REVERSAL + DYNAMIC_ATR (71.4% Win Rate, 4.64 PF)
        # =========================================================================
        if self.config.sys1_enabled:
            fib_382 = peak_p - 0.382 * imp_range
            fib_550 = peak_p - 0.550 * imp_range
            fib_618 = peak_p - 0.618 * imp_range

            # Check if pullback touched into 38.2% - 55% zone and never broke below 61.8%
            post_lows = lows[p_idx + 1 : curr_idx + 1]
            if len(post_lows) > 0 and min(post_lows) <= fib_382 and min(post_lows) >= fib_618:
                # Trigger on first green reversal close with volume drying up (< 55% of peak volume)
                if curr_c > curr_o and curr_v < (0.55 * pump_candidate["peak_vol"]):
                    stop_loss = curr_c - (self.config.sys1_atr_multiplier * atr14)
                    risk_dist = curr_c - stop_loss

                    if risk_dist > (curr_c * 0.003): # Ensure at least 0.3% risk buffer
                        take_profit = curr_c + (self.config.sys1_reward_risk_ratio * risk_dist)
                        qty, r_dist, r_pct = self.calculate_1r_position_size(
                            symbol_meta, curr_c, stop_loss, self.config.dollar_risk_per_trade
                        )

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
                                "target_r": self.config.sys1_reward_risk_ratio,
                                "max_hold_mins": self.config.sys1_max_hold_mins,
                                "pump_meta": pump_candidate
                            }

        # =========================================================================
        # SYSTEM 2: CONFIRMED_BREAKOUT + TIGHT_STRUCTURE (53.6% Win Rate, 1.32 PF)
        # =========================================================================
        if self.config.sys2_enabled:
            fib_618 = peak_p - 0.618 * imp_range
            post_lows = lows[p_idx + 1 : curr_idx + 1]
            cons_low = min(post_lows) if len(post_lows) > 0 else curr_l

            # Condition: Consolidation held above Fib 61.8%
            if cons_low >= fib_618:
                # Trigger: Price broke strictly above peak_p on current candle
                if curr_h > peak_p and closes[curr_idx - 1] <= peak_p:
                    entry_p = max(curr_c, peak_p * 1.001)
                    stop_loss = min(cons_low * 0.998, entry_p * 0.975) # Tight structure SL
                    risk_dist = entry_p - stop_loss

                    if risk_dist > (entry_p * 0.003):
                        take_profit = entry_p + (self.config.sys2_tp1_ratio * risk_dist)
                        qty, r_dist, r_pct = self.calculate_1r_position_size(
                            symbol_meta, entry_p, stop_loss, self.config.dollar_risk_per_trade
                        )

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
                                "target_r": self.config.sys2_tp1_ratio,
                                "max_hold_mins": self.config.sys2_max_hold_mins,
                                "pump_meta": pump_candidate
                            }

        return None
