# Family Quiz App - Todo

## Completed
- [x] Project structure (app.py, templates/, static/)
- [x] SQLite database schema (users, questions, answers)
- [x] Login page with username + password auth
- [x] Auto-registration for new users
- [x] Admin login (admin / admin123)
- [x] Quiz page with unanswered questions
- [x] Users view their answers and total score
- [x] Admin dashboard with leaderboard
- [x] Admin can add questions (3 options + scores)
- [x] Answer details view grouped by user (accordion)
- [x] Leaderboard with ranks, progress bars, and stats
- [x] Docker support (Dockerfile, docker-compose.yml, .dockerignore)
- [x] Favicon (emoji house icon)
- [x] Bootstrap Icons across all pages
- [x] Enhanced UI: gradients, animations, modern cards
- [x] Admin: delete questions (with confirm dialog)
- [x] Admin: Manage Questions tab
- [x] Enhanced dashboard: stat cards, progress bars, tabs
- [x] Quit button in navbar (styled logout)
- [x] Visual score badges (high/low/zero)
- [x] QR code on login page — scan to open app
- [x] Auto-detect local network IP for QR URL
- [x] `/qr` route serving QR code PNG
- [x] Configurable via `PORT` and `APP_URL` env vars


## Deployment readiness (2026-11)
- [x] Hashed, user-chosen passwords (replaces username+123 / admin123)
- [x] Admin password from `ADMIN_PASSWORD` (or generated + logged)
- [x] Legacy account migration
- [x] CSRF protection on all forms
- [x] Persistent generated `SECRET_KEY`, secure cookie flags
- [x] Security headers + CSP, SRI on CDN assets, no inline JS
- [x] Production servers (gunicorn in Docker, waitress for `python app.py`)
- [x] DB initialised under any WSGI server (app factory)
- [x] Non-root Docker image with healthcheck, `/healthz`
- [x] Fixed crashes on malformed/stale quiz submissions
- [x] Leaderboard excludes admin; stale sessions cleared
- [x] Friendly error pages (400/403/404/413/500)
- [x] Question editing, CSV export, reset/delete players, change password
- [x] Automated tests (pytest)

## Planned / Expandable
- [ ] Login rate limiting
- [ ] Admin reset of a player's password
- [ ] Category tags for questions
- [ ] Timed quizzes
- [ ] Multiple quizzes / rounds
- [ ] Pagination for large datasets
