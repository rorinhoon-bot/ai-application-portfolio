"""Local identity, sessions and object policy for new auth-only workspaces."""
import hashlib
import json
import re
import secrets
import sqlite3
import time

from domain import AppError, require

ROLES = ('admin', 'researcher', 'reviewer')
IDLE_SECONDS = 30 * 60
ABSOLUTE_SECONDS = 8 * 60 * 60


def token_hash(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()


class AuthManager:
    def __init__(self, store):
        self.store = store
        with store.transaction() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    role TEXT NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id),
                    csrf TEXT NOT NULL, created_at INTEGER NOT NULL,
                    last_seen INTEGER NOT NULL, absolute_until INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS login_failures (
                    username TEXT PRIMARY KEY, count INTEGER NOT NULL, window_start INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS document_owners (
                    document_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id));
                CREATE TABLE IF NOT EXISTS project_access (
                    project_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(user_id),
                    reviewer_id TEXT NOT NULL REFERENCES users(user_id),
                    CHECK(owner_id != reviewer_id));
                CREATE TABLE IF NOT EXISTS access_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL,
                    user_id TEXT, action TEXT NOT NULL, resource TEXT NOT NULL,
                    outcome TEXT NOT NULL);
            ''')

    def audit(self, actor, action, resource, outcome):
        with self.store.transaction() as connection:
            connection.execute('INSERT INTO access_audit(created_at,user_id,action,resource,outcome) VALUES(?,?,?,?,?)',
                               (int(time.time()), actor['user_id'] if actor else None, action[:48], resource[:100], outcome[:32]))

    def has_admin(self):
        with self.store.transaction() as connection:
            return bool(connection.execute("SELECT 1 FROM users WHERE role='admin' AND enabled=1").fetchone())

    def create_user(self, username, password, role):
        require(type(username) is str and re.fullmatch(r'[a-z][a-z0-9_.-]{2,31}', username), 'INPUT_INVALID')
        require(role in ROLES and type(password) is str and 12 <= len(password) <= 128, 'INPUT_INVALID')
        require(not any(ord(c) < 32 for c in password), 'INPUT_INVALID')
        salt = secrets.token_bytes(16)
        secret = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=1)
        user_id = 'usr-' + secrets.token_hex(16)
        with self.store.transaction() as connection:
            if role != 'admin':
                require(connection.execute("SELECT 1 FROM users WHERE role='admin' AND enabled=1").fetchone(), 'ACCESS_DENIED')
            else:
                require(not connection.execute("SELECT 1 FROM users WHERE role='admin'").fetchone(), 'ACCESS_DENIED')
            try:
                connection.execute('INSERT INTO users(user_id,username,role,salt,password_hash) VALUES(?,?,?,?,?)',
                                   (user_id, username, role, salt, secret))
            except sqlite3.IntegrityError:
                raise AppError('IDEMPOTENCY_CONFLICT') from None
        self.audit({'user_id': user_id}, 'user_created', user_id, 'allowed')
        return {'user_id': user_id, 'username': username, 'role': role}

    def users(self, role=None):
        with self.store.transaction() as connection:
            rows = connection.execute('SELECT user_id,username,role FROM users WHERE enabled=1 ORDER BY username').fetchall()
            return [dict(row) for row in rows if role is None or row['role'] == role]

    def login(self, username, password):
        require(type(username) is str and re.fullmatch(r'[a-z][a-z0-9_.-]{2,31}', username) and
                type(password) is str and len(password) <= 128, 'LOGIN_FAILED')
        try:
            encoded = password.encode('utf-8')
        except UnicodeError:
            raise AppError('LOGIN_FAILED') from None
        now = int(time.time())
        outcome = 'denied'
        token = None
        actor = None
        with self.store.transaction() as connection:
            failure = connection.execute('SELECT * FROM login_failures WHERE username=?', (username,)).fetchone()
            if failure and now - failure['window_start'] < 900 and failure['count'] >= 5:
                outcome = 'locked'
            else:
                row = connection.execute('SELECT * FROM users WHERE username=? AND enabled=1', (username,)).fetchone()
                # One fixed dummy derivation keeps unknown-user failures from taking a fast path.
                salt = row['salt'] if row else b'\0' * 16
                expected = row['password_hash'] if row else b'\0' * 64
                candidate = hashlib.scrypt(encoded, salt=salt, n=16384, r=8, p=1)
                if not row or not secrets.compare_digest(candidate, expected):
                    count = failure['count'] + 1 if failure and now - failure['window_start'] < 900 else 1
                    window = failure['window_start'] if failure and now - failure['window_start'] < 900 else now
                    connection.execute('INSERT OR REPLACE INTO login_failures VALUES(?,?,?)', (username, count, window))
                else:
                    connection.execute('DELETE FROM login_failures WHERE username=?', (username,))
                    token = secrets.token_urlsafe(32)
                    csrf = secrets.token_urlsafe(32)
                    connection.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',
                                       (token_hash(token), row['user_id'], csrf, now, now, now + ABSOLUTE_SECONDS))
                    actor = {'user_id': row['user_id'], 'username': row['username'], 'role': row['role'], 'csrf': csrf}
                    outcome = 'allowed'
        self.audit(actor, 'login', 'session', outcome)
        if outcome != 'allowed':
            raise AppError('LOGIN_LOCKED' if outcome == 'locked' else 'LOGIN_FAILED')
        return token, actor

    def session(self, token):
        if type(token) is not str or len(token) > 128 or not token.isascii():
            return None
        now = int(time.time())
        with self.store.transaction() as connection:
            row = connection.execute('''SELECT s.*,u.username,u.role,u.enabled FROM sessions s
                JOIN users u ON u.user_id=s.user_id WHERE s.token_hash=?''', (token_hash(token),)).fetchone()
            if not row:
                return None
            if not row['enabled'] or now >= row['absolute_until'] or now - row['last_seen'] >= IDLE_SECONDS:
                connection.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(token),))
                return None
            connection.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?', (now, token_hash(token)))
            return {key: row[key] for key in ('user_id', 'username', 'role', 'csrf')}

    def logout(self, token, actor):
        with self.store.transaction() as connection:
            connection.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(token),))
        self.audit(actor, 'logout', 'session', 'allowed')

    def require_role(self, actor, *roles):
        require(actor is not None, 'UNAUTHENTICATED')
        require(actor['role'] in roles, 'ACCESS_DENIED')

    def bind_document(self, document, actor):
        with self.store.transaction() as connection:
            row = connection.execute('SELECT user_id FROM document_owners WHERE document_id=?', (document,)).fetchone()
            if row:
                require(row['user_id'] == actor['user_id'], 'NOT_FOUND')
            else:
                connection.execute('INSERT INTO document_owners VALUES(?,?)', (document, actor['user_id']))

    def document_owner(self, document, actor):
        self.require_role(actor, 'researcher')
        with self.store.transaction() as connection:
            row = connection.execute('SELECT user_id FROM document_owners WHERE document_id=?', (document,)).fetchone()
            require(row is not None and row['user_id'] == actor['user_id'], 'NOT_FOUND')

    def visible_documents(self, actor):
        with self.store.transaction() as connection:
            if actor['role'] == 'admin':
                return {row[0] for row in connection.execute('SELECT document_id FROM document_owners')}
            return {row[0] for row in connection.execute('SELECT document_id FROM document_owners WHERE user_id=?', (actor['user_id'],))}

    def version_access(self, version, actor):
        with self.store.transaction() as connection:
            row = connection.execute('SELECT document_id FROM library_versions WHERE version_id=?', (version,)).fetchone()
            require(row is not None, 'NOT_FOUND')
            if actor['role'] == 'admin':
                return
            owned = connection.execute('SELECT 1 FROM document_owners WHERE document_id=? AND user_id=?',
                                       (row['document_id'], actor['user_id'])).fetchone()
            assigned = any(version in json.loads(item[0]) for item in connection.execute('''
                SELECT p.version_ids_json FROM project_access a JOIN research_projects p ON p.project_id=a.project_id
                WHERE a.reviewer_id=?''', (actor['user_id'],)))
            require(owned or assigned, 'NOT_FOUND')

    def bind_project_in_transaction(self, connection, project, owner, reviewer_id, *, existing=False):
        """Bind only inside the caller's project-creation transaction."""
        self.require_role(owner, 'researcher')
        researcher = connection.execute("SELECT 1 FROM users WHERE user_id=? AND role='researcher' AND enabled=1",
                                        (owner['user_id'],)).fetchone()
        reviewer = connection.execute("SELECT 1 FROM users WHERE user_id=? AND role='reviewer' AND enabled=1",
                                      (reviewer_id,)).fetchone()
        require(researcher and reviewer and reviewer_id != owner['user_id'], 'ACCESS_DENIED')
        row = connection.execute('SELECT owner_id,reviewer_id FROM project_access WHERE project_id=?', (project,)).fetchone()
        if existing:
            # Never claim a legacy orphan project on an idempotent retry.
            require(row is not None and row['owner_id'] == owner['user_id'] and
                    row['reviewer_id'] == reviewer_id, 'NOT_FOUND')
            return
        require(row is None, 'PROJECT_CONFLICT')
        connection.execute('INSERT INTO project_access VALUES(?,?,?)', (project, owner['user_id'], reviewer_id))
        connection.execute('INSERT INTO access_audit(created_at,user_id,action,resource,outcome) VALUES(?,?,?,?,?)',
                           (int(time.time()), owner['user_id'], 'project_bound', project, 'allowed'))

    def project(self, project, actor, *, owner=False, reviewer=False):
        with self.store.transaction() as connection:
            row = connection.execute('SELECT owner_id,reviewer_id FROM project_access WHERE project_id=?', (project,)).fetchone()
            require(row is not None, 'NOT_FOUND')
            require(actor['role'] == 'admin' or actor['user_id'] in (row['owner_id'], row['reviewer_id']), 'NOT_FOUND')
            if owner:
                require(actor['role'] == 'researcher' and row['owner_id'] == actor['user_id'], 'ACCESS_DENIED')
            elif reviewer:
                require(actor['role'] in ('reviewer', 'admin') and row['owner_id'] != actor['user_id'] and
                        (actor['role'] == 'admin' or row['reviewer_id'] == actor['user_id']), 'ACCESS_DENIED')
            else:
                require(actor['role'] == 'admin' or actor['user_id'] in (row['owner_id'], row['reviewer_id']), 'NOT_FOUND')
            return dict(row)

    def visible_projects(self, actor):
        with self.store.transaction() as connection:
            rows = connection.execute('SELECT project_id,owner_id,reviewer_id FROM project_access').fetchall()
            return {row['project_id'] for row in rows if actor['role'] == 'admin' or
                    actor['user_id'] in (row['owner_id'], row['reviewer_id'])}

    def task(self, task, actor, *, owner=False, reviewer=False):
        with self.store.transaction() as connection:
            row = connection.execute('SELECT snapshot_json FROM task_executions WHERE task_id=?', (task,)).fetchone()
            require(row is not None, 'NOT_FOUND')
            project_id = json.loads(row['snapshot_json'])['project_id']
        self.project(project_id, actor, owner=owner, reviewer=reviewer)
        return project_id
