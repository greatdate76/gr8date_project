#!/usr/bin/env bash
set -euo pipefail

# 1) Create & activate venv
PY="${PYTHON:-python3}"
$PY -m venv venv
source venv/bin/activate

# 2) Upgrade pip & install deps
pip install --upgrade pip wheel
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi

# 3) DB & static (safe if already present)
python manage.py migrate --noinput || true
python manage.py collectstatic --noinput || true

# 4) Run
echo
echo "---------------------------------------------------------"
echo "Server starting on http://127.0.0.1:8000"
echo "To stop: press CTRL+C"
echo "---------------------------------------------------------"
echo
python manage.py runserver
