"""
Production WEEX V3 Contract REST API Client.
Handles market data, HMAC-SHA256 authenticated execution, precision rounding, and native TP/SL.
"""

import hmac
import hashlib
import base64
import time
import json
import logging
import requests
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger("weex_dual_bot.client")

class WeexClient:
    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        base_url: str = "https://api-contract.weex.com"
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "WeexDualSystemBot/1.0"
        })
        self._exchange_info_cache: Dict[str, Dict[str, Any]] = {}

    def _generate_signature(self, timestamp: str, method: str, path: str, body_str: str) -> str:
        message = timestamp + method.upper() + path + body_str
        sig = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).digest()
        return base64.b64encode(sig).decode("utf-8")

    def request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        is_public: bool = False,
        timeout: int = 10
    ) -> Tuple[int, Any]:
        url = self.base_url + path
        timestamp = str(int(time.time() * 1000))
        body_str = json.dumps(body, separators=(',', ':')) if (method.upper() not in ["GET", "DELETE"] and body is not None) else ""

        headers = {
            "Content-Type": "application/json"
        }
        if not is_public:
            if not self.api_key or not self.api_secret:
                raise ValueError("API Key and Secret required for private WEEX endpoints.")
            headers["ACCESS-KEY"] = self.api_key
            headers["ACCESS-SIGN"] = self._generate_signature(timestamp, method, path, body_str)
            headers["ACCESS-TIMESTAMP"] = timestamp
            headers["ACCESS-PASSPHRASE"] = self.passphrase

        try:
            resp = self.session.request(
                method=method.upper(),
                url=url,
                headers=headers,
                data=body_str if body_str else None,
                timeout=timeout
            )
            try:
                data = resp.json()
            except Exception:
                data = resp.text

            if resp.status_code >= 400:
                logger.warning(f"WEEX API HTTP {resp.status_code} on {method} {path}: {data}")

            return resp.status_code, data
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error on {method} {path}: {e}")
            raise

    # ---------------- Public Market Data ---------------- #

    def get_24hr_tickers(self) -> List[Dict[str, Any]]:
        status, data = self.request("GET", "/capi/v3/market/ticker/24hr", is_public=True)
        if status == 200 and isinstance(data, list):
            return data
        return []

    def get_exchange_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        if symbol in self._exchange_info_cache:
            return self._exchange_info_cache[symbol]

        status, data = self.request("GET", "/capi/v3/market/exchangeInfo", is_public=True)
        if status != 200:
            return None
        symbols = data.get("symbols", []) or data.get("data", {}).get("symbols", [])
        for s in symbols:
            sym_name = s.get("symbol")
            self._exchange_info_cache[sym_name] = {
                "symbol": sym_name,
                "contractVal": float(s.get("contractVal", 1.0)),
                "minOrderSize": float(s.get("minOrderSize", 0.0001)),
                "pricePrecision": int(s.get("pricePrecision", 2)),
                "quantityPrecision": int(s.get("quantityPrecision", 2)),
                "minLeverage": int(s.get("minLeverage", 1)),
                "maxLeverage": int(s.get("maxLeverage", 50))
            }
        return self._exchange_info_cache.get(symbol)

    def get_klines(self, symbol: str, interval: str = "5m", limit: int = 100) -> List[Dict[str, Any]]:
        path = f"/capi/v3/market/klines?symbol={symbol}&interval={interval}&limit={limit}"
        status, data = self.request("GET", path, is_public=True)
        if status != 200 or not isinstance(data, list):
            return []

        candles = []
        for row in data:
            try:
                candles.append({
                    "timestamp": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "quote_volume": float(row[7]) if len(row) > 7 else float(row[5]) * float(row[4])
                })
            except (ValueError, IndexError):
                continue

        candles.sort(key=lambda x: x["timestamp"])
        return candles

    def get_mark_price(self, symbol: str) -> Optional[float]:
        status, data = self.request("GET", f"/capi/v3/market/premiumIndex?symbol={symbol}", is_public=True)
        if status == 200:
            if isinstance(data, list):
                for item in data:
                    if item.get("symbol") == symbol:
                        return float(item.get("markPrice", 0))
            elif isinstance(data, dict):
                return float(data.get("data", {}).get("markPrice") or data.get("markPrice", 0))
        return None

    # ---------------- Private Account & Execution ---------------- #

    def get_available_margin(self) -> float:
        status, data = self.request("GET", "/capi/v3/account/balance")
        if status != 200:
            return 0.0
        balances = data if isinstance(data, list) else (data.get("data", []) if isinstance(data, dict) else [])
        for asset in balances:
            if asset.get("asset") == "USDT":
                return float(asset.get("availableBalance") or asset.get("balance") or 0.0)
        return 0.0

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        payload = {
            "symbol": symbol,
            "isolatedLongLeverage": str(leverage),
            "isolatedShortLeverage": str(leverage)
        }
        status, _ = self.request("POST", "/capi/v3/account/leverage", body=payload)
        return status == 200

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        status, data = self.request("GET", "/capi/v3/account/position/allPosition")
        if status != 200:
            return []
        positions = data if isinstance(data, list) else (data.get("data", []) if isinstance(data, dict) else [])
        active = []
        for p in positions:
            size = float(p.get("size") or p.get("total") or 0)
            if size > 0 and (not symbol or p.get("symbol") == symbol):
                active.append({
                    "symbol": p.get("symbol"),
                    "side": p.get("side", "LONG"),
                    "size": size,
                    "entry_price": float(p.get("entryPrice", 0)),
                    "unrealized_pnl": float(p.get("unrealizePnl", 0))
                })
        return active

    def place_market_order(
        self,
        symbol: str,
        side: str,             # 'BUY' or 'SELL'
        position_side: str,    # 'LONG' or 'SHORT'
        quantity: float,
        client_order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        cid = client_order_id or f"b-d-{int(time.time()*1000)}"
        eff_pos_side = position_side if position_side in ("LONG", "SHORT") else ("LONG" if side.upper() == "BUY" else "SHORT")

        payload = {
            "symbol": symbol,
            "side": side.upper(),
            "positionSide": eff_pos_side,
            "type": "MARKET",
            "quantity": str(quantity),
            "newClientOrderId": cid
        }
        logger.info(f"Submitting WEEX Market Order: {side} {quantity} {symbol} (positionSide={eff_pos_side})")
        status, data = self.request("POST", "/capi/v3/order", body=payload)
        
        if status == 200 and isinstance(data, dict) and (data.get("success") or data.get("orderId")):
            return {"success": True, "orderId": str(data.get("orderId")), "clientOrderId": cid}
        
        err_msg = data.get("msg") if isinstance(data, dict) else str(data)
        logger.error(f"Failed to submit market order on {symbol}: status {status}, err: {err_msg}")
        return {"success": False, "error": err_msg}

    def place_native_tpsl_plan_order(
        self,
        symbol: str,
        plan_type: str,        # 'TAKE_PROFIT' or 'STOP_LOSS'
        trigger_price: float,
        position_side: str = "LONG"
    ) -> bool:
        cid = f"b-p-{plan_type[:2].lower()}-{int(time.time()*1000)}"
        payload = {
            "symbol": symbol,
            "clientAlgoId": cid,
            "planType": plan_type,
            "triggerPrice": str(trigger_price),
            "positionSide": position_side,
            "executePrice": "0",  # Market execution upon trigger
            "quantity": "0",      # 0 = whole-position protection on WEEX
            "triggerPriceType": "CONTRACT_PRICE"
        }
        logger.info(f"Submitting Native Plan Order on WEEX: {plan_type} @ {trigger_price} ({position_side})")
        status, data = self.request("POST", "/capi/v3/placeTpSlOrder", body=payload)
        item = data[0] if isinstance(data, list) else data
        return status == 200 and isinstance(item, dict) and bool(item.get("success") or item.get("orderId"))

    def close_market_position(self, symbol: str, side: str, position_side: str, quantity: float) -> bool:
        cid = f"b-close-{int(time.time()*1000)}"
        payload = {
            "symbol": symbol,
            "side": side.upper(),
            "positionSide": position_side,
            "type": "MARKET",
            "quantity": str(quantity),
            "newClientOrderId": cid
        }
        status, data = self.request("POST", "/capi/v3/order", body=payload)
        return status == 200
