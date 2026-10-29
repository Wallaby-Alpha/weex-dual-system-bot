# WEEX Dual-System Momentum Trading Bot (1R = $1.00 USD)

A production-grade algorithmic trading daemon designed to scan the top liquid altcoin perpetual contracts on **WEEX**, detect 5-minute explosive pump events, and execute high-probability momentum continuations with **exact 1R = $1.00 USD risk sizing** and **real-time Telegram alerts**.

---

## The Dual Trading System Architecture

Based on empirical backtesting across **399,961 candlesticks (400 symbols)** on WEEX, this bot trades two complementary momentum systems:

```
                  [Explosive 5m Pump: Gain >= 8%, Vol >= 3.5x]
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
        [Route A: Deep Retrace (38-55%)]      [Route B: Shallow Retrace (<35%)]
                    │                                     │
           Pullback Volume < 55%                 Price breaks Peak High
                    │                                     │
           First Green 5m Close                  Stop-Market Buy at Peak + 0.1%
                    │                                     │
    System 1: FIB50 Reversal + ATR SL      System 2: Confirmed Breakout + Tight SL
    • Win Rate: 71.4%                     • Win Rate: 53.6%
    • Profit Factor: 4.64                 • Profit Factor: 1.32
    • Target: 1.5R (Avg Duration: 58m)    • Target: 1.5R (Avg Duration: 27m)
```

### Risk Management: Exact 1R = $1.00 USD Sizing
For every trade, position size is calculated dynamically:
$$\text{Quantity} = \frac{\$1.00}{\left| P_{\text{entry}} - P_{\text{stop}} \right| \times \text{contractVal}}$$
The quantity is automatically rounded to the exchange's `quantityPrecision` and validated against `minOrderSize`.

---

## Project Structure

```
weex-dual-system-bot/
├── config.py                 # Environment configuration loader
├── weex_client.py            # WEEX V3 Contract REST API client with HMAC-SHA256 signing
├── strategy_engine.py        # System 1 & System 2 detection logic & 1R sizing
├── risk_manager.py           # Position monitoring, concurrency, TP/SL & time stops
├── telegram_notifier.py      # Real-time Telegram alert delivery engine
├── main.py                   # Master daemon polling loop
├── test_bot.py               # Pre-flight diagnostics & connectivity verification
├── .env.example              # Template for API keys & Telegram tokens
├── requirements.txt          # Python dependencies
├── deploy.sh                 # One-click Ubuntu / DigitalOcean setup script
├── weex-dual-bot.service     # Linux systemd background service definition
├── Dockerfile                # Docker container configuration
└── docker-compose.yml        # Docker compose configuration
```

---

## Quick Start (Local Verification)

### 1. Setup Virtual Environment
```bash
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy the template and fill in your keys:
```bash
cp .env.example .env
```
Key settings in `.env`:
* `DRY_RUN=True`: Test in paper-trading mode first. Set to `False` for real money execution.
* `DOLLAR_RISK=1.00`: Sets 1R to exactly $1.00 USD.
* `WEEX_API_KEY`, `WEEX_API_SECRET`, `WEEX_PASSPHRASE`: Your WEEX contract API keys.
* `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`: For instant Telegram alerts.

### 3. Run Pre-Flight Diagnostics
```bash
python test_bot.py
```
This tests:
1. WEEX Public REST Market Data connectivity.
2. Exact 1R = $1.00 USD position sizing math across different contract types.
3. Private WEEX credentials (if supplied).
4. Telegram alert delivery.

---

## Pushing to a New GitHub Repository

From your local machine, run:
```bash
cd scratch/weex-dual-system-bot

# 1. Initialize git
git init
git add .
git commit -m "feat: WEEX Dual-System Trading Bot with 1R=$1 risk sizing and Telegram alerts"

# 2. Add your GitHub remote (replace with your repo URL)
git remote add origin https://github.com/<your-username>/<your-repo-name>.git
git branch -M main
git push -u origin main
```

---

## Deploying to a DigitalOcean Droplet

### Step 1: Create a DigitalOcean Droplet
1. Log into [DigitalOcean](https://cloud.digitalocean.com/).
2. Click **Create** $\rightarrow$ **Droplets**.
3. Choose:
   * **OS**: **Ubuntu 22.04 LTS** or **Ubuntu 24.04 LTS**.
   * **Plan**: **Basic** (Regular SSD, $4/month or $6/month is more than enough).
   * **Datacenter**: Choose **Singapore**, **Frankfurt**, or **New York** (close to exchange servers).
   * **Authentication**: SSH Key (recommended) or Password.
4. Click **Create Droplet**.

### Step 2: SSH into the Droplet & Clone Repo
```bash
ssh root@<YOUR_DROPLET_IP>

# Clone your GitHub repository
git clone https://github.com/<your-username>/<your-repo-name>.git
cd <your-repo-name>
```

### Step 3: Run the Automated Deployment Script
```bash
chmod +x deploy.sh
./deploy.sh
```
This will:
* Install Python 3, pip, and venv.
* Install all dependencies from `requirements.txt`.
* Create your `.env` configuration file.
* Install and configure the `systemd` daemon service.

### Step 4: Add Your Keys in `.env`
```bash
nano .env
```
Fill in your `WEEX_API_KEY`, `WEEX_API_SECRET`, `WEEX_PASSPHRASE`, and `TELEGRAM_BOT_TOKEN`.
Save and exit with `CTRL + O`, `ENTER`, `CTRL + X`.

### Step 5: Test Diagnostics on the Droplet
```bash
venv/bin/python test_bot.py
```
You should see:
```
[TEST 1] Testing WEEX Public REST Market Data... SUCCESS
[TEST 2] Testing Exact 1R = $1.00 USD Position Sizing Math... SUCCESS
[TEST 3] Testing Private WEEX Account Credentials... AUTHENTICATED! Available USDT Balance: $XXX
[TEST 4] Testing Telegram Bot Notification Delivery... SUCCESS (Test message delivered!)
```

### Step 6: Start the 24/7 Background Service
```bash
sudo systemctl start weex-dual-bot
```

### Managing the Background Service
* **Check live status**: `sudo systemctl status weex-dual-bot`
* **Stream real-time logs**: `sudo journalctl -u weex-dual-bot -f`
* **Restart service**: `sudo systemctl restart weex-dual-bot`
* **Stop service**: `sudo systemctl stop weex-dual-bot`

---

## Telegram Alert Examples

When running, the bot sends real-time formatted notifications:

### 1. Bot Startup Alert
> 🚀 **WEEX DUAL-SYSTEM BOT ACTIVATED**
> • **Status**: 🟢 LIVE EXECUTION
> • **Risk Unit (1R)**: `$1.00 USD`
> • **Available USDT**: `$250.00`
> • **Scanned Universe**: `60 Altcoins`
> • **Active Systems**:
>   1. *FIB50 Reversal + Dynamic ATR* (71.4% WR, 4.64 PF)
>   2. *Confirmed Breakout + Tight Flag* (53.6% WR, 1.32 PF)

### 2. Trade Entry Alert
> 🟢 **TRADE OPENED: AINUSDT (LONG)**
> • **System**: `System 1: FIB50 Reversal + Dynamic ATR`
> • **Entry Price**: `0.0489`
> • **Sized Qty**: `285 AINUSDT`
> • **Stop Loss**: `0.0454 (-7.16%)`
> • **Take Profit**: `0.0542 (+10.74%)`
> • **Position Risk (1R)**: `$1.00 USD`
> • **Target R:R**: `1.5:1`

### 3. Trade Exit Alert
> 🎯 **POSITION CLOSED: AINUSDT [PROFIT]**
> • **Exit Reason**: `TAKE_PROFIT`
> • **Entry Price**: `0.0489`
> • **Exit Price**: `0.0542`
> • **Net Realized PnL**: `+$1.50 USD`
> • **Outcome**: `+1.50R`
