# Family Quiz

A small web app for running a scored multiple-choice quiz with your family. The admin writes
questions with three options (A/B/C) and gives each option a number of points. Players sign in on
their phones by scanning the QR code on the login page. They answer the questions, and the admin
sees a live leaderboard.

## Features

- **Players:** sign in with your name and a password you choose (the account is created the first
  time you log in), answer all open questions at once, see your score and answers, and change
  your password.
- **Admin:** dashboard with stats, a leaderboard, every player's answers, and question
  add/edit/delete. Admins can reset a player's answers so they can play again, delete players,
  and export the results to CSV.
- **QR code** on the login page so everyone can open the app on their phone.
- **Security:** hashed passwords, CSRF protection, a secure session cookie, CSP and other
  security headers, and escaped user content.

## Quick start (Docker — recommended)

```bash
cp .env.example .env        # then edit ADMIN_PASSWORD and APP_URL
docker compose up -d --build
```

Open `http://<your-computer-ip>:5000` and log in as **admin** with your `ADMIN_PASSWORD`.
Data lives in the `quiz_data` Docker volume. `GET /healthz` is the health check endpoint.

> Inside Docker the app can't see your LAN IP, so set `APP_URL` (for example
> `http://192.168.1.50:5000`) to make the QR code point to the right address.

## Run without Docker

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip ...
ADMIN_PASSWORD=choose-a-strong-one python app.py
```

`python app.py` serves with **waitress** on Windows. On Linux/macOS, use gunicorn:

```bash
gunicorn --preload -w 2 --threads 4 -b 0.0.0.0:5000 "app:create_app()"
```

For development with auto-reload and the debugger, set `FLASK_DEBUG=1`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ADMIN_PASSWORD` | *(generated)* | Password for the `admin` account (at least 8 characters). It is applied every time the app starts. If unset, a random password is generated on first start and printed to the log. |
| `SECRET_KEY` | *(generated)* | Signs session cookies. If unset, a random key is created and saved as `.secret_key` next to the database. |
| `DATABASE_PATH` | `quiz.db` | SQLite database file. |
| `APP_URL` | auto | URL encoded in the QR code. If unset, the app uses the request host, or the machine's LAN IP when accessed via localhost. |
| `PORT` | `5000` | Port to listen on. |
| `ALLOW_REGISTRATION` | `true` | Allow new players to create an account by logging in with a new name. |
| `SESSION_COOKIE_SECURE` | `false` | Set to `true` when serving over HTTPS. |
| `TRUST_PROXY` | `false` | Set to `true` behind a reverse proxy that sends `X-Forwarded-*` headers. |
| `FLASK_DEBUG` | `false` | Use the Flask development server with the debugger. Never set this in production. |

## Deploying on the internet

The app is fine on a home network as is. To expose it publicly:

1. Put it behind an HTTPS reverse proxy (Caddy, nginx, Traefik, or a managed platform).
2. Set `SESSION_COOKIE_SECURE=true`, `TRUST_PROXY=true` and `APP_URL=https://your-domain`.
3. Use a strong `ADMIN_PASSWORD`. Consider `ALLOW_REGISTRATION=false` once everyone has an
   account.
4. Add login rate limiting at the proxy. The app does not throttle login attempts itself.
5. Back up the database: copy `quiz.db` from the data volume.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Upgrading from the earlier version

Earlier versions used the password *username + "123"* and `admin123` for the admin. Existing
databases are migrated automatically:

- The admin password becomes `ADMIN_PASSWORD`, or a generated password if that is unset.
- Existing players can log in once with their old password and are then asked to choose a new one.
