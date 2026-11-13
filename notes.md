# Family Quiz App - Developer Notes

See `README.md` for setup, configuration and deployment.

## Architecture
- **Single-file Flask app** (`app.py`) built with an app factory, `create_app(config)`. All routes
  are on the `main` blueprint, so templates use `url_for('main.<view>')`.
- **SQLite** in WAL mode. The schema and migrations run in `init_db()` on every start, and both
  are idempotent.
- **Bootstrap 5 and Bootstrap Icons** from jsDelivr, pinned with SRI hashes. `static/app.js`
  replaces inline JS so the CSP can disallow inline scripts.
- **Flask-WTF CSRFProtect.** Every POST form includes `csrf_token()`.
- **Production servers:** gunicorn (`--preload`) in Docker and waitress for `python app.py`.

## Authentication
- Passwords are hashed with Werkzeug's `generate_password_hash`.
- Usernames are matched case-insensitively. Logging in with an unknown name creates the account
  (when `ALLOW_REGISTRATION` is on) with the password entered, which must be at least 4 characters.
- The admin account is `admin`. Its password comes from `ADMIN_PASSWORD` and is re-applied at
  every start. If that is unset, a random password is generated once and logged.
- Legacy accounts (no `password_hash`) are accepted once with `username + "123"` and then sent to
  the change-password page.

## Database Schema
```
users:     id, username (unique), is_admin, password_hash, created_at
questions: id, text, opt_a, opt_b, opt_c, score_a, score_b, score_c
answers:   id, user_id (FK), question_id (FK), selected_option (A|B|C), UNIQUE(user_id, question_id)
```

## Routes
| Route | Access | Purpose |
|-------|--------|---------|
| `/login` | Public | Login and self-registration |
| `/logout` | Any | Clear session (the navbar sends a POST) |
| `/qr` | Public | QR code PNG for the app URL |
| `/healthz` | Public | Health check |
| `/account/password` | Logged in | Change password |
| `/quiz` | Player | Answer questions, view score |
| `/admin/dashboard` | Admin | Stats, leaderboard, answers, questions |
| `/admin/add_question` | Admin | Add question ("Save & Add Another" supported) |
| `/admin/questions/<id>/edit` | Admin | Edit question |
| `/admin/delete_question/<id>` | Admin (POST) | Delete question and its answers |
| `/admin/users/<id>/reset_answers` | Admin (POST) | Clear a player's answers |
| `/admin/users/<id>/delete` | Admin (POST) | Delete a player |
| `/admin/export.csv` | Admin | Download results (formula-injection safe) |

## Scoring
Each option has an integer score, which can be negative. A player's total is the sum of the
scores of the options they chose. Answers are final once submitted; the admin can reset them.
The leaderboard excludes admins.
