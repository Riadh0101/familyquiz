"""Family Quiz — a small Flask app for running scored multiple-choice quizzes at home.

Run locally:      python app.py
Run in production: gunicorn --preload -b 0.0.0.0:5000 "app:create_app()"
"""
import csv
import io
import logging
import os
import secrets
import socket
import sqlite3
from collections import defaultdict
from functools import wraps

import qrcode
from flask import (Blueprint, Flask, abort, current_app, flash, g, redirect, render_template,
                   request, send_file, session, url_for, Response)
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

USERNAME_MAX = 50
USER_PASSWORD_MIN = 4
ADMIN_PASSWORD_MIN = 8
TEXT_MAX = 500
OPTIONS = ('A', 'B', 'C')

csrf = CSRFProtect()
bp = Blueprint('main', __name__)

# SQL fragment: score of the option a user picked (requires aliases a = answers, q = questions).
SELECTED_SCORE = """CASE a.selected_option
    WHEN 'A' THEN q.score_a WHEN 'B' THEN q.score_b WHEN 'C' THEN q.score_c END"""
SELECTED_TEXT = """CASE a.selected_option
    WHEN 'A' THEN q.opt_a WHEN 'B' THEN q.opt_b WHEN 'C' THEN q.opt_c END"""


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


# --------------------------------------------------------------------------- app factory

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.environ.get('DATABASE_PATH', 'quiz.db'),
        APP_URL=os.environ.get('APP_URL') or None,
        PORT=int(os.environ.get('PORT', 5000)),
        ADMIN_PASSWORD=os.environ.get('ADMIN_PASSWORD') or None,
        ALLOW_REGISTRATION=_env_flag('ALLOW_REGISTRATION', True),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=_env_flag('SESSION_COOKIE_SECURE', False),
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
        MAX_CONTENT_LENGTH=256 * 1024,
        WTF_CSRF_TIME_LIMIT=None,  # token lives as long as the session
    )
    if test_config:
        app.config.update(test_config)

    app.secret_key = app.config.get('SECRET_KEY') or os.environ.get('SECRET_KEY') \
        or _load_or_create_secret(app.config['DATABASE'])

    if _env_flag('TRUST_PROXY'):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.logger.setLevel(logging.INFO)

    csrf.init_app(app)
    app.register_blueprint(bp)
    app.teardown_appcontext(close_db)
    app.after_request(_security_headers)
    for code in (400, 403, 404, 413, 500):
        app.register_error_handler(code, _error_page)

    init_db(app)
    return app


def _load_or_create_secret(db_path):
    """Persist a random secret next to the database so sessions survive restarts."""
    key_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), '.secret_key')
    try:
        with open(key_path, encoding='utf-8') as fh:
            key = fh.read().strip()
            if key:
                return key
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    try:
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(key)
    except FileExistsError:  # another process won the race
        with open(key_path, encoding='utf-8') as fh:
            return fh.read().strip()
    return key


def _security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'self'")
    return response


def _error_page(error):
    code = getattr(error, 'code', 500) or 500
    messages = {
        400: 'The request could not be processed. Your session may have expired — please try again.',
        403: "You don't have access to that page.",
        404: "We couldn't find that page.",
        413: 'That request was too large.',
        500: 'Something went wrong on our side.',
    }
    return render_template('error.html', code=code,
                           message=messages.get(code, 'Something went wrong.')), code


# --------------------------------------------------------------------------- database

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    is_admin INTEGER DEFAULT 0,
    password_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    opt_a TEXT NOT NULL,
    opt_b TEXT NOT NULL,
    opt_c TEXT NOT NULL,
    score_a INTEGER DEFAULT 0,
    score_b INTEGER DEFAULT 0,
    score_c INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    selected_option TEXT NOT NULL CHECK(selected_option IN ('A', 'B', 'C')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (question_id) REFERENCES questions(id),
    UNIQUE(user_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_answers_question ON answers(question_id);
"""


def init_db(app):
    db_path = app.config['DATABASE']
    db_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(db_dir, exist_ok=True)

    db = sqlite3.connect(db_path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(SCHEMA)
        # Migration for databases created before passwords were stored.
        columns = {row['name'] for row in db.execute("PRAGMA table_info(users)")}
        if 'password_hash' not in columns:
            db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        _ensure_admin(app, db)
        db.commit()
    finally:
        db.close()


def _ensure_admin(app, db):
    admin = db.execute("SELECT * FROM users WHERE username = 'admin' COLLATE NOCASE").fetchone()
    if not admin:
        db.execute("INSERT INTO users (username, is_admin) VALUES ('admin', 1)")
        admin = db.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
    elif not admin['is_admin']:
        db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (admin['id'],))

    configured = app.config.get('ADMIN_PASSWORD')
    if configured:
        if len(configured) < ADMIN_PASSWORD_MIN:
            raise RuntimeError(f'ADMIN_PASSWORD must be at least {ADMIN_PASSWORD_MIN} characters.')
        if not (admin['password_hash'] and check_password_hash(admin['password_hash'], configured)):
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(configured), admin['id']))
    elif not admin['password_hash']:
        generated = secrets.token_urlsafe(9)
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                   (generate_password_hash(generated), admin['id']))
        app.logger.warning("No ADMIN_PASSWORD set. Generated admin password: %s "
                           "(log in as 'admin' and change it, or set ADMIN_PASSWORD).", generated)


# --------------------------------------------------------------------------- helpers

def current_user():
    if 'user' not in g:
        g.user = None
        if 'user_id' in session:
            g.user = get_db().execute("SELECT * FROM users WHERE id = ?",
                                      (session['user_id'],)).fetchone()
            if g.user is None:  # account was deleted or DB reset
                session.clear()
    return g.user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for('main.login'))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for('main.login'))
        if not user['is_admin']:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def _is_local_host(host):
    hostname = host.split(':')[0].strip('[]').lower()
    return hostname in ('localhost', '0.0.0.0', '::1') or hostname.startswith('127.')


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packets are sent; this only picks the outbound interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def get_app_url():
    """URL encoded in the login-page QR code."""
    configured = current_app.config.get('APP_URL')
    if configured:
        return configured.rstrip('/')
    if request and not _is_local_host(request.host):
        return request.host_url.rstrip('/')
    return f"http://{get_local_ip()}:{current_app.config['PORT']}"


def _log_in(user):
    session.clear()  # prevent session fixation
    session.permanent = True
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['is_admin'] = bool(user['is_admin'])


def _home_for(user):
    return url_for('main.admin_dashboard') if user['is_admin'] else url_for('main.quiz')


def _read_question_form(form):
    """Validate the add/edit question form. Returns (values, error)."""
    values = {k: form.get(k, '').strip() for k in ('text', 'opt_a', 'opt_b', 'opt_c')}
    scores = {}
    for k in ('score_a', 'score_b', 'score_c'):
        raw = form.get(k, '').strip() or '0'
        try:
            scores[k] = int(raw)
        except ValueError:
            return {**values, **{s: form.get(s, '') for s in ('score_a', 'score_b', 'score_c')}}, \
                'Scores must be whole numbers.'
    values.update(scores)
    if not all(values[k] for k in ('text', 'opt_a', 'opt_b', 'opt_c')):
        return values, 'All fields are required.'
    if any(len(values[k]) > TEXT_MAX for k in ('text', 'opt_a', 'opt_b', 'opt_c')):
        return values, f'Text fields must be {TEXT_MAX} characters or fewer.'
    if any(abs(v) > 1_000_000 for v in scores.values()):
        return values, 'Scores must be between -1,000,000 and 1,000,000.'
    return values, None


# --------------------------------------------------------------------------- routes: public

@bp.route('/')
def index():
    user = current_user()
    return redirect(_home_for(user) if user else url_for('main.login'))


@bp.route('/healthz')
def healthz():
    get_db().execute("SELECT 1").fetchone()
    return {'status': 'ok'}


@bp.route('/qr')
def qr_code():
    img = qrcode.make(get_app_url())
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    response = send_file(buf, mimetype='image/png')
    response.headers['Cache-Control'] = 'no-cache'
    return response


@bp.route('/login', methods=['GET', 'POST'])
def login():
    user = current_user()
    if user and request.method == 'GET':
        return redirect(_home_for(user))

    error = None
    username = ''
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()

        if not username:
            error = 'Username is required.'
        elif len(username) > USERNAME_MAX:
            error = f'Username must be {USERNAME_MAX} characters or fewer.'
        elif not password:
            error = 'Password is required.'
        else:
            user = db.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                              (username,)).fetchone()
            if user is None:
                if not current_app.config['ALLOW_REGISTRATION']:
                    error = 'Unknown username. Ask the quiz admin to create your account.'
                elif len(password) < USER_PASSWORD_MIN:
                    error = f'Choose a password of at least {USER_PASSWORD_MIN} characters.'
                else:
                    db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                               (username, generate_password_hash(password)))
                    db.commit()
                    user = db.execute("SELECT * FROM users WHERE username = ?",
                                      (username,)).fetchone()
                    current_app.logger.info("Registered new user %r", username)
                    flash(f'Welcome, {user["username"]}! Your account has been created — '
                          'remember your password.', 'success')
                    _log_in(user)
                    return redirect(_home_for(user))
            elif user['password_hash'] is None:
                # Account from the old version (password was username + "123"): upgrade it.
                if not user['is_admin'] and password == user['username'] + '123':
                    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                               (generate_password_hash(password), user['id']))
                    db.commit()
                    flash('Please choose a new password for your account.', 'warning')
                    _log_in(user)
                    return redirect(url_for('main.change_password'))
                error = 'Invalid username or password.'
            elif check_password_hash(user['password_hash'], password):
                _log_in(user)
                return redirect(_home_for(user))
            else:
                current_app.logger.info("Failed login for %r from %s", username, request.remote_addr)
                error = 'Invalid username or password.'

    return render_template('login.html', error=error, username=username,
                           app_url=get_app_url(),
                           allow_registration=current_app.config['ALLOW_REGISTRATION'],
                           password_min=USER_PASSWORD_MIN), (400 if error else 200)


@bp.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    return redirect(url_for('main.login'))


@bp.route('/account/password', methods=['GET', 'POST'])
@login_required
def change_password():
    user = current_user()
    error = None
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        minimum = ADMIN_PASSWORD_MIN if user['is_admin'] else USER_PASSWORD_MIN
        if not user['password_hash'] or not check_password_hash(user['password_hash'], current):
            error = 'Your current password is incorrect.'
        elif len(new) < minimum:
            error = f'The new password must be at least {minimum} characters.'
        elif new != confirm:
            error = 'The new passwords do not match.'
        elif new == current:
            error = 'The new password must be different from the current one.'
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(new), user['id']))
            db.commit()
            flash('Password changed.', 'success')
            return redirect(_home_for(user))
    return render_template('change_password.html', error=error,
                           minimum=ADMIN_PASSWORD_MIN if user['is_admin'] else USER_PASSWORD_MIN,
                           env_admin=bool(user['is_admin'] and current_app.config.get('ADMIN_PASSWORD'))
                           ), (400 if error else 200)


# --------------------------------------------------------------------------- routes: player

@bp.route('/quiz', methods=['GET', 'POST'])
@login_required
def quiz():
    db = get_db()
    user_id = current_user()['id']

    if request.method == 'POST':
        valid_ids = {row['id'] for row in db.execute("SELECT id FROM questions")}
        saved = 0
        for raw_id in request.form.getlist('question_id'):
            try:
                qid = int(raw_id)
            except ValueError:
                continue
            selected = request.form.get(f'question_{qid}')
            if qid in valid_ids and selected in OPTIONS:
                cur = db.execute(
                    "INSERT OR IGNORE INTO answers (user_id, question_id, selected_option) "
                    "VALUES (?, ?, ?)", (user_id, qid, selected))
                saved += cur.rowcount
        db.commit()
        if saved:
            flash(f'Saved {saved} answer{"s" if saved != 1 else ""}.', 'success')
        else:
            flash('No new answers were saved.', 'warning')
        return redirect(url_for('main.quiz'))

    unanswered = db.execute("""
        SELECT * FROM questions q
        WHERE NOT EXISTS (SELECT 1 FROM answers a WHERE a.question_id = q.id AND a.user_id = ?)
        ORDER BY q.id
    """, (user_id,)).fetchall()

    my_answers = db.execute(f"""
        SELECT q.id, q.text, a.selected_option,
               {SELECTED_TEXT} AS option_text, {SELECTED_SCORE} AS score
        FROM answers a JOIN questions q ON q.id = a.question_id
        WHERE a.user_id = ?
        ORDER BY q.id
    """, (user_id,)).fetchall()
    total_score = sum(a['score'] or 0 for a in my_answers)

    return render_template('quiz.html', questions=unanswered,
                           my_answers=my_answers, total_score=total_score)


# --------------------------------------------------------------------------- routes: admin

def _leaderboard(db):
    return db.execute(f"""
        SELECT u.id, u.username, u.created_at,
               COALESCE(SUM({SELECTED_SCORE}), 0) AS total_score,
               COUNT(a.id) AS answers_count
        FROM users u
        LEFT JOIN answers a ON a.user_id = u.id
        LEFT JOIN questions q ON q.id = a.question_id
        WHERE u.is_admin = 0
        GROUP BY u.id
        ORDER BY total_score DESC, answers_count DESC, u.username COLLATE NOCASE
    """).fetchall()


@bp.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db()
    leaderboard = _leaderboard(db)
    questions = db.execute("SELECT * FROM questions ORDER BY id").fetchall()

    all_answers = db.execute(f"""
        SELECT u.username, q.text AS question_text, a.selected_option,
               {SELECTED_TEXT} AS option_text, {SELECTED_SCORE} AS score
        FROM answers a
        JOIN users u ON u.id = a.user_id
        JOIN questions q ON q.id = a.question_id
        WHERE u.is_admin = 0
        ORDER BY u.username COLLATE NOCASE, q.id
    """).fetchall()
    grouped_answers = defaultdict(list)
    for a in all_answers:
        grouped_answers[a['username']].append(a)

    answer_counts = {row['question_id']: row['cnt'] for row in db.execute(
        "SELECT question_id, COUNT(*) AS cnt FROM answers GROUP BY question_id")}

    return render_template('dashboard.html',
                           leaderboard=leaderboard,
                           grouped_answers=dict(grouped_answers),
                           questions=questions,
                           question_count=len(questions),
                           answer_counts=answer_counts)


@bp.route('/admin/add_question', methods=['GET', 'POST'])
@admin_required
def add_question():
    values, error = {}, None
    if request.method == 'POST':
        values, error = _read_question_form(request.form)
        if not error:
            db = get_db()
            db.execute(
                "INSERT INTO questions (text, opt_a, opt_b, opt_c, score_a, score_b, score_c) "
                "VALUES (:text, :opt_a, :opt_b, :opt_c, :score_a, :score_b, :score_c)", values)
            db.commit()
            flash('Question added.', 'success')
            if request.form.get('add_another'):
                return redirect(url_for('main.add_question'))
            return redirect(url_for('main.admin_dashboard') + '#questions')
    return render_template('question_form.html', error=error, q=values, editing=False), \
        (400 if error else 200)


@bp.route('/admin/questions/<int:question_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_question(question_id):
    db = get_db()
    question = db.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    if question is None:
        abort(404)
    values, error = dict(question), None
    if request.method == 'POST':
        values, error = _read_question_form(request.form)
        if not error:
            db.execute(
                "UPDATE questions SET text = :text, opt_a = :opt_a, opt_b = :opt_b, opt_c = :opt_c, "
                "score_a = :score_a, score_b = :score_b, score_c = :score_c WHERE id = :id",
                {**values, 'id': question_id})
            db.commit()
            flash('Question updated.', 'success')
            return redirect(url_for('main.admin_dashboard') + '#questions')
    answered = db.execute("SELECT COUNT(*) FROM answers WHERE question_id = ?",
                          (question_id,)).fetchone()[0]
    return render_template('question_form.html', error=error, q=values, editing=True,
                           question_id=question_id, answered=answered), (400 if error else 200)


@bp.route('/admin/delete_question/<int:question_id>', methods=['POST'])
@admin_required
def delete_question(question_id):
    db = get_db()
    db.execute("DELETE FROM answers WHERE question_id = ?", (question_id,))
    cur = db.execute("DELETE FROM questions WHERE id = ?", (question_id,))
    db.commit()
    flash('Question deleted.' if cur.rowcount else 'That question no longer exists.',
          'success' if cur.rowcount else 'warning')
    return redirect(url_for('main.admin_dashboard') + '#questions')


@bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    if user['is_admin']:
        flash("The admin account can't be deleted.", 'danger')
    else:
        db.execute("DELETE FROM answers WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        flash(f'Player "{user["username"]}" and their answers were deleted.', 'success')
    return redirect(url_for('main.admin_dashboard'))


@bp.route('/admin/users/<int:user_id>/reset_answers', methods=['POST'])
@admin_required
def reset_answers(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    db.execute("DELETE FROM answers WHERE user_id = ?", (user_id,))
    db.commit()
    flash(f'Answers for "{user["username"]}" were cleared — they can play again.', 'success')
    return redirect(url_for('main.admin_dashboard'))


@bp.route('/admin/export.csv')
@admin_required
def export_csv():
    db = get_db()
    rows = db.execute(f"""
        SELECT u.username, q.id AS question_id, q.text AS question, a.selected_option,
               {SELECTED_TEXT} AS answer, {SELECTED_SCORE} AS score
        FROM answers a
        JOIN users u ON u.id = a.user_id
        JOIN questions q ON q.id = a.question_id
        WHERE u.is_admin = 0
        ORDER BY u.username COLLATE NOCASE, q.id
    """).fetchall()

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['username', 'question_id', 'question', 'option', 'answer', 'score'])
    for r in rows:
        writer.writerow([_csv_safe(r['username']), r['question_id'], _csv_safe(r['question']),
                         r['selected_option'], _csv_safe(r['answer']), r['score']])
    return Response('﻿' + out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=family-quiz-results.csv'})


def _csv_safe(value):
    """Stop spreadsheet apps from treating user text as a formula."""
    value = '' if value is None else str(value)
    return "'" + value if value[:1] in ('=', '+', '-', '@', '\t', '\r') else value


def main():
    application = create_app()
    port = application.config['PORT']
    if _env_flag('FLASK_DEBUG'):
        application.run(debug=True, host='0.0.0.0', port=port)
        return
    try:
        from waitress import serve
    except ImportError:
        application.logger.warning('waitress is not installed; using the Flask development server.')
        application.run(host='0.0.0.0', port=port)
    else:
        application.logger.info('Family Quiz running on http://0.0.0.0:%s', port)
        serve(application, host='0.0.0.0', port=port, threads=8)


if __name__ == '__main__':
    main()
