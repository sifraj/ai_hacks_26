#!/bin/bash
# =============================================================================
# setup.sh — First-time project setup
# Run once after cloning the repo
# =============================================================================

set -e

echo "🏦 Crypto Hedge Fund — Setup"
echo "================================"

# Check prerequisites
command -v python3 >/dev/null 2>&1 || { echo "❌ Python 3.11+ required"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "❌ Docker required"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "❌ Docker Compose required (docker compose, not docker-compose)"; exit 1; }
command -v node >/dev/null 2>&1 || { echo "❌ Node.js 18+ required (for dashboard)"; exit 1; }

echo "✅ Prerequisites OK"

# Copy .env if not exists — back up any existing one first as a safety net
if [ -f .env ]; then
  backup=".env.backup.$(date +%Y%m%d%H%M%S)"
  cp .env "$backup"
  echo "✅ .env already exists — backed up to $backup before doing anything else"
else
  cp .env.example .env
  echo "⚠️  Created .env from template — FILL IN YOUR API KEYS before starting"
fi

# Create log directory
mkdir -p logs

# Create KILL_SWITCH file placeholder reference
echo "ℹ️  To trigger emergency kill switch: touch ./KILL_SWITCH"

# Start Docker services
echo ""
echo "🐳 Starting Docker services (TimescaleDB + Redis)..."
docker compose up -d
echo "⏳ Waiting for services to be healthy..."
sleep 5

# Check health
docker compose ps

# Install Python dependencies
echo ""
echo "🐍 Installing Python dependencies..."
pip install -r requirements.txt

# Install dashboard dependencies
echo ""
echo "⚛️  Installing dashboard dependencies..."
cd dashboard && npm install && cd ..

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env and add your API keys"
echo "  2. Run: bash scripts/start.sh"
