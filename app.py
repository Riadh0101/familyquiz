import sqlite3
from flask import Flask, render_template, request, redirect, session, url_for, g
from functools import wraps
from collections import defaultdict
import os

app = Flask(__name__)
app.secret_key = 'family-quiz-secret-key-change-in-production'
DATABASE = os.environ.get('DATABASE_PATH', 'quiz.db')


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            is_admin INTEGER DEFAULT 0,
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
    """)
    cur = db.execute("SELECT id FROM users WHERE username = ?", ('admin',))
    if not cur.fetchone():
        db.execute("INSERT INTO users (username, is_admin) VALUES (?, 1)", ('admin',))
    db.commit()
    db.close()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        db = get_db()
        user = db.execute("SELECT is_admin FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        if not user or not user['is_admin']:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    if 'user_id' in session:
        db = get_db()
        user = db.execute("SELECT is_admin FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        if user and user['is_admin']:
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('quiz'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        error = None

        if not username:
            error = 'Username is required.'
        else:
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

            if not user:
                db.execute("INSERT INTO users (username) VALUES (?)", (username,))
                db.commit()
                user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

            expected_password = 'admin123' if user['is_admin'] else (username + '123')

            if password != expected_password:
                error = 'Invalid password.'
            else:
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['is_admin'] = bool(user['is_admin'])
                if user['is_admin']:
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('quiz'))

        return render_template('login.html', error=error)

    return render_template('login.html', error=None)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/quiz', methods=['GET', 'POST'])
@login_required
def quiz():
    db = get_db()
    user_id = session['user_id']

    if request.method == 'POST':
        question_ids = request.form.getlist('question_id')
        for qid in question_ids:
            selected = request.form.get(f'question_{qid}')
            if selected in ('A', 'B', 'C'):
                db.execute(
                    "INSERT OR IGNORE INTO answers (user_id, question_id, selected_option) VALUES (?, ?, ?)",
                    (user_id, int(qid), selected)
                )
        db.commit()
        return redirect(url_for('quiz'))

    questions = db.execute("SELECT * FROM questions ORDER BY id").fetchall()
    user_answers = db.execute(
        "SELECT question_id, selected_option FROM answers WHERE user_id = ?", (user_id,)
    ).fetchall()
    answered_qids = {a['question_id'] for a in user_answers}

    unanswered = [q for q in questions if q['id'] not in answered_qids]

    total_score = db.execute("""
        SELECT COALESCE(SUM(
            CASE a.selected_option
                WHEN 'A' THEN q.score_a
                WHEN 'B' THEN q.score_b
                WHEN 'C' THEN q.score_c
            END
        ), 0) as total
        FROM answers a
        JOIN questions q ON q.id = a.question_id
        WHERE a.user_id = ?
    """, (user_id,)).fetchone()['total']

    my_answers = db.execute("""
        SELECT q.id, q.text,
            a.selected_option,
            CASE a.selected_option
                WHEN 'A' THEN q.opt_a
                WHEN 'B' THEN q.opt_b
                WHEN 'C' THEN q.opt_c
            END as option_text,
            CASE a.selected_option
                WHEN 'A' THEN q.score_a
                WHEN 'B' THEN q.score_b
                WHEN 'C' THEN q.score_c
            END as score
        FROM answers a
        JOIN questions q ON q.id = a.question_id
        WHERE a.user_id = ?
        ORDER BY q.id
    """, (user_id,)).fetchall()

    return render_template('quiz.html',
                         questions=unanswered,
                         my_answers=my_answers,
                         total_score=total_score)


@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db()

    leaderboard = db.execute("""
        SELECT u.id, u.username,
            COALESCE(SUM(
                CASE a.selected_option
                    WHEN 'A' THEN q.score_a
                    WHEN 'B' THEN q.score_b
                    WHEN 'C' THEN q.score_c
                END
            ), 0) as total_score,
            COUNT(a.id) as answers_count
        FROM users u
        LEFT JOIN answers a ON a.user_id = u.id
        LEFT JOIN questions q ON q.id = a.question_id
        GROUP BY u.id
        ORDER BY total_score DESC, u.username
    """).fetchall()

    question_count = db.execute("SELECT COUNT(*) as cnt FROM questions").fetchone()['cnt']

    all_answers = db.execute("""
        SELECT u.username, q.text as question_text, a.selected_option,
            CASE a.selected_option
                WHEN 'A' THEN q.opt_a
                WHEN 'B' THEN q.opt_b
                WHEN 'C' THEN q.opt_c
            END as option_text,
            CASE a.selected_option
                WHEN 'A' THEN q.score_a
                WHEN 'B' THEN q.score_b
                WHEN 'C' THEN q.score_c
            END as score,
            q.score_a, q.score_b, q.score_c
        FROM answers a
        JOIN users u ON u.id = a.user_id
        JOIN questions q ON q.id = a.question_id
        ORDER BY u.username, q.id
    """).fetchall()

    grouped_answers = defaultdict(list)
    for a in all_answers:
        grouped_answers[a['username']].append(a)

    questions = db.execute("SELECT * FROM questions ORDER BY id").fetchall()

    return render_template('dashboard.html',
                         leaderboard=leaderboard,
                         grouped_answers=dict(grouped_answers),
                         questions=questions,
                         question_count=question_count)


@app.route('/admin/delete_question/<int:question_id>', methods=['POST'])
@admin_required
def delete_question(question_id):
    db = get_db()
    db.execute("DELETE FROM answers WHERE question_id = ?", (question_id,))
    db.execute("DELETE FROM questions WHERE id = ?", (question_id,))
    db.commit()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/add_question', methods=['GET', 'POST'])
@admin_required
def add_question():
    if request.method == 'POST':
        text = request.form.get('text', '').strip()
        opt_a = request.form.get('opt_a', '').strip()
        opt_b = request.form.get('opt_b', '').strip()
        opt_c = request.form.get('opt_c', '').strip()

        try:
            score_a = int(request.form.get('score_a', 0))
            score_b = int(request.form.get('score_b', 0))
            score_c = int(request.form.get('score_c', 0))
        except ValueError:
            return render_template('add_question.html', error='Scores must be integers.')

        if not all([text, opt_a, opt_b, opt_c]):
            return render_template('add_question.html', error='All fields are required.')

        db = get_db()
        db.execute(
            "INSERT INTO questions (text, opt_a, opt_b, opt_c, score_a, score_b, score_c) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (text, opt_a, opt_b, opt_c, score_a, score_b, score_c)
        )
        db.commit()
        return redirect(url_for('admin_dashboard'))

    return render_template('add_question.html', error=None)


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
