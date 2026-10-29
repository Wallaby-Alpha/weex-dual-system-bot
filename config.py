"""
Configuration Loader for WEEX Dual-System Trading Bot.
Loads credentials, risk settings, and scanning parameters from environment variables.
"""

import os
from dataclasses import dataclass, field
from typing import Set, List
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

@dataclass
class BotConfig:
    # --- WEEX API Credentials ---
    api_key: str = os.getenv("WEEX_API_KEY", "")
    api_secret: str = os.getenv("WEEX_API_SECRET", "")
    passphrase: str = os.getenv("WEEX_PASSPHRASE", "")
    base_url: str = os.getenv("WEEX_BASE_URL", "https://api-contract.weex.com").rstrip("/")
    
    # --- Trading Mode ---
    # Set DRY_RUN=False in production to execute real orders with real money
    dry_run: bool = os.getenv("DRY_RUN", "True").lower() in ("true", "1", "yes")
    
    # --- Risk Management: 1R = $1.00 USD ---
    dollar_risk_per_trade: float = float(os.getenv("DOLLAR_RISK", "1.00")) # 1R = $1.00
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "3"))    # Concurrency limit
    default_leverage: int = int(os.getenv("DEFAULT_LEVERAGE", "10"))       # 10x leverage
    
    # --- Telegram Notification Settings ---
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_enabled: bool = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
    
    # --- Market Scanner Universe ---
    top_n_universe: int = int(os.getenv("TOP_N_UNIVERSE", "60"))           # Scan top 60 volume altcoins
    quote_asset: str = "USDT"
    scan_interval_sec: int = int(os.getenv("SCAN_INTERVAL_SEC", "30"))     # Loop every 30 seconds
    
    # Exclude majors and stablecoins (focus on altcoin runners)
    excluded_symbols: Set[str] = field(default_factory=lambda: {
        "USDCUSDT", "TUSDUSDT", "FDUSDUSDT", "EURUSDT", "DAIUSDT", 
        "USDEUSDT", "BUSDUSDT", "USDPUSDT", "AEURUSDT", "USDUSDT", 
        "WBTCUSDT", "BTCUSDT", "ETHUSDT"
    })
    
    # --- Pump Detection Criteria ---
    min_pump_gain_pct: float = float(os.getenv("MIN_PUMP_GAIN_PCT", "8.0")) # +8.0% minimum surge
    min_volume_spike_ratio: float = float(os.getenv("MIN_VOL_SPIKE", "3.5")) # >= 3.5x 20-period median
    min_quote_vol_usdt: float = float(os.getenv("MIN_QUOTE_VOL", "30000.0")) # >= $30,000 turnover
    
    # --- System 1: FIB50_REVERSAL + DYNAMIC_ATR Settings ---
    sys1_enabled: bool = os.getenv("SYS1_ENABLED", "True").lower() in ("true", "1", "yes")
    sys1_atr_multiplier: float = 1.5      # SL = Entry - 1.5x ATR-14
    sys1_reward_risk_ratio: float = 1.5   # TP = Entry + 1.5R
    sys1_max_hold_mins: int = 60          # 60 mins time stop
    
    # --- System 2: CONFIRMED_BREAKOUT + TIGHT_STRUCTURE Settings ---
    sys2_enabled: bool = os.getenv("SYS2_ENABLED", "True").lower() in ("true", "1", "yes")
    sys2_tp1_ratio: float = 1.5           # TP1: 50% exit at 1.5R
    sys2_tp2_ratio: float = 2.5           # TP2: 50% exit at 2.5R
    sys2_max_hold_mins: int = 45          # 45 mins time stop
    
    # --- Logging ---
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

config = BotConfig()
