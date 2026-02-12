#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
DB_PATH="${DB_PATH:-$ROOT_DIR/rewardmaximiser.db}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
CARDS_FILE="${CARDS_FILE:-$ROOT_DIR/data/cards.sample.json}"
BANK_OFFERS_FILE="${BANK_OFFERS_FILE:-$ROOT_DIR/data/bank_offers.sample.json}"
SOCIAL_OFFERS_FILE="${SOCIAL_OFFERS_FILE:-$ROOT_DIR/data/social_offers.sample.json}"

log() {
  printf '[deploy] %s\n' "$*"
}

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    printf '[deploy] missing %s file: %s\n' "$label" "$path" >&2
    exit 1
  fi
}

log "Preparing Python virtual environment at $VENV_DIR"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

log "Installing project dependencies"
if ! python -m pip install --no-build-isolation --no-deps -e "$ROOT_DIR" >/dev/null 2>&1; then
  log "Editable install skipped (offline/build backend unavailable); using source path"
fi

export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

require_file "$CARDS_FILE" "cards"
require_file "$BANK_OFFERS_FILE" "bank offers"
require_file "$SOCIAL_OFFERS_FILE" "social offers"

log "Syncing cards into SQLite database"
python "$ROOT_DIR/agent.py" --db "$DB_PATH" sync-cards --cards "$CARDS_FILE"

log "Refreshing offer sources"
python "$ROOT_DIR/agent.py" --db "$DB_PATH" --bank-offers "$BANK_OFFERS_FILE" --social-offers "$SOCIAL_OFFERS_FILE" refresh

export HF_API_KEY="${HF_API_KEY:-}"
export HF_MODEL="${HF_MODEL:-mistralai/Mistral-7B-Instruct-v0.2}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.1:8b}"

log "Environment ready"
log "Starting web app on http://$HOST:$PORT"
exec python "$ROOT_DIR/agent.py" --db "$DB_PATH" web --host "$HOST" --port "$PORT"
