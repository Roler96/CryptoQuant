#!/bin/bash
# CryptoQuant Deployment Script
# Usage: bash deploy/install.sh

set -euo pipefail

APP_DIR="/opt/cryptoquant"
VENV_DIR="$APP_DIR/.venv"

echo "=== CryptoQuant Deployment ==="

# 1. Create user
if ! id -u cryptoquant &>/dev/null; then
    echo "Creating cryptoquant user..."
    sudo useradd -r -s /bin/false -d "$APP_DIR" cryptoquant
fi

# 2. Create directories
echo "Setting up directories..."
sudo mkdir -p "$APP_DIR" "$APP_DIR/data" "$APP_DIR/logs" "$APP_DIR/state"
sudo chown -R cryptoquant:cryptoquant "$APP_DIR"

# 3. Copy application files
echo "Copying application files..."
sudo cp -r cryptoquant/ live_runner.py config.yaml pyproject.toml "$APP_DIR/"
sudo cp -r strategies/ "$APP_DIR/" 2>/dev/null || true

# 4. Install Python dependencies
echo "Installing Python dependencies..."
if ! command -v uv &>/dev/null; then
    sudo pip install uv
fi

cd "$APP_DIR"
sudo -u cryptoquant uv sync --frozen

# 5. Copy .env if not exists
if [ ! -f "$APP_DIR/.env" ]; then
    echo ""
    echo "WARNING: No .env file found."
    echo "Copy .env.example to .env and fill in your API credentials:"
    echo "  sudo cp .env.example .env"
    echo "  sudo nano .env"
    echo ""
fi

# 6. Install systemd service
echo "Installing systemd service..."
sudo cp deploy/cryptoquant.service /etc/systemd/system/
sudo systemctl daemon-reload

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit $APP_DIR/.env with your API credentials"
echo "  2. Review $APP_DIR/config.yaml"
echo "  3. Start: sudo systemctl start cryptoquant"
echo "  4. Status: sudo systemctl status cryptoquant"
echo "  5. Logs: sudo journalctl -u cryptoquant -f"
echo ""
