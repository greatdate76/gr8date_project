GR8DATE — Unzip & Run

1) Open Terminal and cd into this folder (the one with manage.py).
2) Run:
   ./bootstrap.sh

What it does:
- Creates a local Python virtualenv
- Installs requirements
- Applies any pending migrations
- Collects static files
- Starts the dev server at http://127.0.0.1:8000

Notes:
- Database: db.sqlite3 included.
- Images: static/ and media/ included.
- If Python 3 isn't default, try: PYTHON=python3.11 ./bootstrap.sh
