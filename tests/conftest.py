import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, get_db  # noqa: E402

ADMIN_PASSWORD = 'test-admin-pass'


@pytest.fixture
def make_app(tmp_path):
    def _make(**overrides):
        config = {
            'TESTING': True,
            'DATABASE': str(tmp_path / 'quiz.db'),
            'SECRET_KEY': 'test-secret',
            'ADMIN_PASSWORD': ADMIN_PASSWORD,
            'WTF_CSRF_ENABLED': False,
        }
        config.update(overrides)
        return create_app(config)
    return _make


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password})


@pytest.fixture
def admin_client(client):
    resp = login(client, 'admin', ADMIN_PASSWORD)
    assert resp.status_code == 302
    return client


@pytest.fixture
def add_question(app):
    def _add(text='Q?', a='A1', b='B1', c='C1', sa=10, sb=5, sc=0):
        with app.app_context():
            db = get_db()
            cur = db.execute(
                "INSERT INTO questions (text, opt_a, opt_b, opt_c, score_a, score_b, score_c) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (text, a, b, c, sa, sb, sc))
            db.commit()
            return cur.lastrowid
    return _add


@pytest.fixture
def query(app):
    def _query(sql, args=()):
        with app.app_context():
            return [dict(r) for r in get_db().execute(sql, args).fetchall()]
    return _query
