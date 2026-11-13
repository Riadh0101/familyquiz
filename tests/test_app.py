import re
import sqlite3

from app import create_app
from conftest import ADMIN_PASSWORD, login


# ---------------------------------------------------------------- auth

def test_unauthenticated_pages_redirect_to_login(client):
    for path in ('/', '/quiz', '/admin/dashboard', '/admin/add_question', '/account/password'):
        resp = client.get(path)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/login')


def test_new_user_registers_with_chosen_password(client, query):
    resp = login(client, 'Alice', 'secret1')
    assert resp.status_code == 302 and resp.headers['Location'].endswith('/quiz')
    user = query("SELECT * FROM users WHERE username = 'Alice'")[0]
    assert user['password_hash'] and 'secret1' not in user['password_hash']

    client.post('/logout')
    assert login(client, 'Alice', 'wrong').status_code == 400
    assert login(client, 'Alice', 'secret1').status_code == 302


def test_username_lookup_is_case_insensitive(client, query):
    login(client, 'Alice', 'secret1')
    client.post('/logout')
    assert login(client, 'alice', 'secret1').status_code == 302
    assert len(query("SELECT * FROM users WHERE username LIKE 'alice'")) == 1


def test_old_convention_password_no_longer_works(client):
    login(client, 'bob', 'mypassword')
    client.post('/logout')
    assert login(client, 'bob', 'bob123').status_code == 400


def test_short_password_rejected_and_no_account_created(client, query):
    resp = login(client, 'carol', 'abc')
    assert resp.status_code == 400
    assert b'at least 4 characters' in resp.data
    assert query("SELECT * FROM users WHERE username = 'carol'") == []


def test_wrong_password_for_existing_user_does_not_log_in(client):
    login(client, 'dave', 'goodpass')
    client.post('/logout')
    login(client, 'dave', 'badpass')
    assert client.get('/quiz').status_code == 302


def test_registration_can_be_disabled(make_app):
    client = make_app(ALLOW_REGISTRATION=False).test_client()
    resp = login(client, 'eve', 'whatever')
    assert resp.status_code == 400
    assert b'Ask the quiz admin' in resp.data


def test_admin_password_comes_from_config(client):
    assert login(client, 'admin', 'admin123').status_code == 400
    resp = login(client, 'admin', ADMIN_PASSWORD)
    assert resp.headers['Location'].endswith('/admin/dashboard')


def test_admin_password_generated_when_not_configured(make_app, caplog):
    make_app(ADMIN_PASSWORD=None)
    match = re.search(r'Generated admin password: (\S+)', caplog.text)
    assert match
    client = make_app(ADMIN_PASSWORD=None).test_client()  # second start must not regenerate
    assert login(client, 'admin', match.group(1)).status_code == 302


def test_legacy_accounts_are_migrated(tmp_path):
    db_path = tmp_path / 'legacy.db'
    db = sqlite3.connect(db_path)
    db.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                            is_admin INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO users (username, is_admin) VALUES ('admin', 1), ('grandma', 0);
    """)
    db.commit()
    db.close()

    app = create_app({'TESTING': True, 'DATABASE': str(db_path), 'SECRET_KEY': 'x',
                      'ADMIN_PASSWORD': ADMIN_PASSWORD, 'WTF_CSRF_ENABLED': False})
    client = app.test_client()
    resp = login(client, 'grandma', 'grandma123')
    assert resp.headers['Location'].endswith('/account/password')
    assert login(client, 'admin', 'admin123').status_code == 400


def test_session_for_deleted_user_is_cleared(client, admin_client, app, query):
    other = app.test_client()
    login(other, 'frank', 'frankpw')
    uid = query("SELECT id FROM users WHERE username = 'frank'")[0]['id']
    admin_client.post(f'/admin/users/{uid}/delete')
    assert other.get('/quiz').status_code == 302


def test_non_admin_gets_403_on_admin_pages(client):
    login(client, 'gina', 'ginapw')
    assert client.get('/admin/dashboard').status_code == 403
    assert client.post('/admin/delete_question/1').status_code == 403
    assert client.get('/admin/export.csv').status_code == 403


def test_change_password(client):
    login(client, 'hank', 'oldpass')
    assert client.post('/account/password', data={
        'current_password': 'wrong', 'new_password': 'newpass', 'confirm_password': 'newpass'
    }).status_code == 400
    assert client.post('/account/password', data={
        'current_password': 'oldpass', 'new_password': 'newpass', 'confirm_password': 'nope'
    }).status_code == 400
    assert client.post('/account/password', data={
        'current_password': 'oldpass', 'new_password': 'newpass', 'confirm_password': 'newpass'
    }).status_code == 302
    client.post('/logout')
    assert login(client, 'hank', 'oldpass').status_code == 400
    assert login(client, 'hank', 'newpass').status_code == 302


# ---------------------------------------------------------------- CSRF & headers

def test_csrf_required_on_posts(make_app):
    client = make_app(WTF_CSRF_ENABLED=True).test_client()
    assert login(client, 'ivan', 'ivanpw').status_code == 400

    page = client.get('/login').get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    resp = client.post('/login', data={'username': 'ivan', 'password': 'ivanpw', 'csrf_token': token})
    assert resp.status_code == 302


def test_security_headers(client):
    resp = client.get('/login')
    assert resp.headers['X-Frame-Options'] == 'DENY'
    assert 'default-src' in resp.headers['Content-Security-Policy']
    assert b'admin123' not in resp.data


def test_health_and_qr(client):
    assert client.get('/healthz').get_json() == {'status': 'ok'}
    resp = client.get('/qr')
    assert resp.status_code == 200 and resp.mimetype == 'image/png'


def test_qr_url_uses_configured_app_url(make_app):
    client = make_app(APP_URL='https://quiz.example.com/').test_client()
    assert b'</i>https://quiz.example.com\n' in client.get('/login').data


def test_qr_url_uses_request_host_when_not_local(client):
    resp = client.get('/login', base_url='http://192.168.1.20:5000')
    assert b'</i>http://192.168.1.20:5000\n' in resp.data


def test_unknown_page_renders_404(client):
    resp = client.get('/nope')
    assert resp.status_code == 404 and b'Error 404' in resp.data


# ---------------------------------------------------------------- quiz

def test_quiz_flow_and_scoring(client, add_question, query):
    q1 = add_question('Capital of France?', 'Paris', 'Rome', 'Oslo', 10, 0, 0)
    q2 = add_question('2+2?', '3', '4', '5', 0, 7, 0)
    login(client, 'jill', 'jillpw')

    page = client.get('/quiz').get_data(as_text=True)
    assert 'Capital of France?' in page and '2 questions remaining' in page

    resp = client.post('/quiz', data={'question_id': [q1, q2],
                                      f'question_{q1}': 'A', f'question_{q2}': 'B'})
    assert resp.status_code == 302
    page = client.get('/quiz').get_data(as_text=True)
    assert 'All questions answered!' in page
    assert '>17<' in page.replace(' ', '').replace('\n', '')


def test_answers_cannot_be_changed_after_submission(client, add_question, query):
    q = add_question()
    login(client, 'kim', 'kimpw')
    client.post('/quiz', data={'question_id': q, f'question_{q}': 'A'})
    client.post('/quiz', data={'question_id': q, f'question_{q}': 'C'})
    rows = query("SELECT selected_option FROM answers")
    assert rows == [{'selected_option': 'A'}]


def test_quiz_post_ignores_bad_input(client, add_question, query):
    q = add_question()
    login(client, 'leo', 'leopw')
    resp = client.post('/quiz', data={'question_id': ['abc', '9999', q],
                                      'question_9999': 'A', f'question_{q}': 'Z'})
    assert resp.status_code == 302
    assert query("SELECT * FROM answers") == []


def test_quiz_shows_empty_state_without_questions(client):
    login(client, 'mia', 'miapw')
    assert b"hasn't started yet" in client.get('/quiz').data


def test_user_input_is_escaped(client, add_question):
    add_question(text='<script>alert(1)</script>')
    login(client, 'ned', 'nedpw')
    page = client.get('/quiz').get_data(as_text=True)
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;' in page


# ---------------------------------------------------------------- admin

def test_admin_add_edit_delete_question(admin_client, query):
    resp = admin_client.post('/admin/add_question', data={
        'text': 'Fav color?', 'opt_a': 'Red', 'opt_b': 'Blue', 'opt_c': 'Green',
        'score_a': '1', 'score_b': '2', 'score_c': '-3'})
    assert resp.status_code == 302
    q = query("SELECT * FROM questions")[0]
    assert (q['text'], q['score_c']) == ('Fav color?', -3)

    assert admin_client.get(f"/admin/questions/{q['id']}/edit").status_code == 200
    admin_client.post(f"/admin/questions/{q['id']}/edit", data={
        'text': 'Favourite colour?', 'opt_a': 'Red', 'opt_b': 'Blue', 'opt_c': 'Green',
        'score_a': '5', 'score_b': '2', 'score_c': '0'})
    assert query("SELECT text, score_a FROM questions")[0] == {'text': 'Favourite colour?', 'score_a': 5}

    admin_client.post(f"/admin/delete_question/{q['id']}")
    assert query("SELECT * FROM questions") == []


def test_add_question_validation_keeps_input(admin_client, query):
    resp = admin_client.post('/admin/add_question', data={
        'text': 'Keep me', 'opt_a': 'x', 'opt_b': '', 'opt_c': 'z',
        'score_a': '1', 'score_b': '2', 'score_c': '3'})
    assert resp.status_code == 400
    assert b'All fields are required' in resp.data and b'Keep me' in resp.data

    resp = admin_client.post('/admin/add_question', data={
        'text': 't', 'opt_a': 'x', 'opt_b': 'y', 'opt_c': 'z',
        'score_a': 'ten', 'score_b': '2', 'score_c': '3'})
    assert resp.status_code == 400 and b'whole numbers' in resp.data
    assert query("SELECT * FROM questions") == []


def test_edit_missing_question_404(admin_client):
    assert admin_client.get('/admin/questions/999/edit').status_code == 404


def test_dashboard_leaderboard_excludes_admin(app, admin_client, add_question):
    q = add_question(sa=10)
    player = app.test_client()
    login(player, 'olga', 'olgapw')
    player.post('/quiz', data={'question_id': q, f'question_{q}': 'A'})

    page = admin_client.get('/admin/dashboard').get_data(as_text=True)
    assert '1 player' in page and 'olga' in page
    leaderboard = page.split('id="leaderboard"')[1].split('id="details"')[0]
    assert '>admin<' not in leaderboard.replace(' ', '')


def test_delete_and_reset_user(app, admin_client, add_question, query):
    q = add_question()
    player = app.test_client()
    login(player, 'pat', 'patpw')
    player.post('/quiz', data={'question_id': q, f'question_{q}': 'B'})
    uid = query("SELECT id FROM users WHERE username = 'pat'")[0]['id']

    admin_client.post(f'/admin/users/{uid}/reset_answers')
    assert query("SELECT * FROM answers") == []
    assert query("SELECT * FROM users WHERE id = ?", (uid,))

    admin_client.post(f'/admin/users/{uid}/delete')
    assert query("SELECT * FROM users WHERE id = ?", (uid,)) == []


def test_admin_cannot_be_deleted(admin_client, query):
    admin_id = query("SELECT id FROM users WHERE username = 'admin'")[0]['id']
    admin_client.post(f'/admin/users/{admin_id}/delete')
    assert query("SELECT * FROM users WHERE id = ?", (admin_id,))


def test_csv_export(app, admin_client, add_question):
    q = add_question(text='=HYPERLINK("x")', sa=3)
    player = app.test_client()
    login(player, 'quinn', 'quinnpw')
    player.post('/quiz', data={'question_id': q, f'question_{q}': 'A'})

    resp = admin_client.get('/admin/export.csv')
    assert resp.mimetype == 'text/csv'
    body = resp.get_data(as_text=True)
    assert 'username,question_id,question,option,answer,score' in body
    assert 'quinn' in body and ',3' in body
    assert "'=HYPERLINK" in body  # formula injection neutralised


def test_secret_key_persisted_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    cfg = {'TESTING': True, 'DATABASE': str(tmp_path / 'q.db'), 'ADMIN_PASSWORD': ADMIN_PASSWORD}
    first = create_app(cfg).secret_key
    second = create_app(cfg).secret_key
    assert first == second and len(first) == 64
    assert (tmp_path / '.secret_key').exists()
