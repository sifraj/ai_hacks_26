#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "Crypto Hedge Fund — Setup"
echo "================================"

# Copy .env if not exists — back up any existing one first as a safety net
if [ -f .env ]; then
  backup=".env.backup.$(date +%Y%m%d%H%M%S)"
  cp .env "$backup"
  echo ".env already exists — backed up to $backup before doing anything else"
else
  cp .env.example .env
  echo "Created .env from template — fill in API keys before starting"
fi

# Start Docker services
echo "Starting Docker services..."
docker compose up -d

echo "Waiting for services to be healthy..."
sleep 5
docker compose ps

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

echo ""
echo "Setup complete!"
echo "  1. Edit .env and add your API keys"
echo "  2. Run: uvicorn src.api.main:app --reload"
