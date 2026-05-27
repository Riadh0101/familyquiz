# Family Quiz App - Notes

## Architecture
- **Single-file Flask app** (`app.py`) — easy to understand and modify
- **SQLite** (`quiz.db`) — zero-config, auto-created on first run
- **Bootstrap 5** (CDN) — responsive UI without build tooling
- **Jinja2 templates** with inheritance from `base.html`

## Authentication
| User | Password |
|------|----------|
| Regular user (`{username}`) | `{username}123` |
| Admin (`admin`) | `admin123` |

New users are auto-registered on first successful login.

## Database Schema (3 tables)
```
users:    id, username, is_admin, created_at
questions: id, text, opt_a, opt_b, opt_c, score_a, score_b, score_c
answers:  id, user_id (FK), question_id (FK), selected_option
```

## Key Routes
| Route | Access | Purpose |
|-------|--------|---------|
| `/login` | Public | Login form |
| `/quiz` | Users | Answer questions, view score |
| `/admin/dashboard` | Admin | Leaderboard + answer details |
| `/admin/add_question` | Admin | Add quiz question |
| `/logout` | Any | Clear session |

## How Scoring Works
Each question has three options. Each option has a score value (can be 0 or any integer). The user's total score is the sum of all their selected options' scores. This allows flexible scoring (e.g., correct=10, wrong=0, or opinion-based scoring).

## Security Notes
- No CSRF protection (family use only)
- Passwords derived by convention, not hashed
- Session secret key is hardcoded — change in production
- SQLite database is local and not exposed

## Running the App

### Local (no Docker)
```bash
pip install -r requirements.txt
python app.py
```
Opens at `http://localhost:5000`

### Docker
```bash
docker compose up --build
```
Or build & run manually:
```bash
docker build -t family-quiz .
docker run -p 5000:5000 -v quiz_data:/app/data -e DATABASE_PATH=/app/data/quiz.db family-quiz
```

### Configuration
| Env Var | Default | Description |
|---------|---------|-------------|
| `DATABASE_PATH` | `quiz.db` | Path to SQLite database file |
| `FLASK_ENV` | — | Set to `production` for production mode |
