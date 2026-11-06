# Contributing

Use Python 3.13 and Node.js 24. Create a virtual environment, install
`requirements.lock.txt`, run `npm ci`, then `npm run build`.
Run `python -m pytest -q` with the virtual environment's Python before a pull request.
Tests use a disposable SQLite database and do not require real model credentials.

Windows desktop build: `scripts/build-desktop.ps1`. Keep changes small, describe user-visible
behavior, and include relevant validation. Never add real credentials or personal data.
