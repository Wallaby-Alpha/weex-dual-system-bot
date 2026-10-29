#!/usr/bin/env bash
# ==============================================================================
# One-Click Setup Script for WEEX Dual-System Trading Bot on DigitalOcean
# Compatible with Ubuntu 22.04 LTS / Ubuntu 24.04 LTS
# ==============================================================================

set -e

echo "=========================================================="
echo "🚀 Installing WEEX Dual-System Trading Bot on DigitalOcean"
echo "=========================================================="

# 1. Update OS and install python tools
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl

# 2. Setup virtual environment
if [ ! -d "venv" ]; then
    echo "[*] Creating Python virtual environment..."
    python3 -m venv venv
fi

# 3. Install dependencies
echo "[*] Installing Python packages from requirements.txt..."
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# 4. Check for .env file
if [ ! -f ".env" ]; then
    echo "[!] No .env file found. Creating from .env.example..."
    cp .env.example .env
    echo "[IMPORTANT] Please edit .env with: nano .env before starting the bot!"
fi

# 5. Setup systemd service
echo "[*] Configuring systemd background daemon service..."
sudo cp weex-dual-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable weex-dual-bot

echo ""
echo "=========================================================="
echo "✅ Setup Complete!"
echo "=========================================================="
echo "Next steps:"
echo "1. Configure your keys: nano .env"
echo "2. Run test verification: venv/bin/python test_bot.py"
echo "3. Start background service: sudo systemctl start weex-dual-bot"
echo "4. View live logs: sudo journalctl -u weex-dual-bot -f"
echo "=========================================================="
