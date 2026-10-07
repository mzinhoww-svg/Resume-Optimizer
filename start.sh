#!/usr/bin/env bash
# Sobe o backend do Resume Optimizer em http://127.0.0.1:8000
set -e
cd "$(dirname "$0")/backend"
if [ ! -f .env ] && [ -z "$OPENROUTER_API_KEY" ]; then
  echo "Falta a OPENROUTER_API_KEY. Defina a variavel de ambiente ou crie backend/.env com: OPENROUTER_API_KEY=sua_chave" >&2
  exit 1
fi
exec ../.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --reload
