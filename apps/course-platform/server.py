"""Loopback-only HTTP application for the offline course platform."""
import argparse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import socket
import sys
import webbrowser

from domain import APP, AppError, decode, require
from service import Service

ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/projects.js": ("projects.js", "text/javascript; charset=utf-8"),
          "/library.js": ("library.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8")}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port, service):
        if service.auth_required:
            require(service.auth.has_admin(), 'STATE_UNSAFE')
        self.service = service
        self.csrf = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server_version = "CoursePlatform"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        # Do not log question text, token, headers, runtime paths or raw exceptions.
        return

    def drain_rejected_body(self):
        """Consume a bounded, already-sent POST body before closing on Windows."""
        if self.command != 'POST' or getattr(self, '_body_read', False):
            return
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or not lengths[0].isdigit() or self.headers.get('Transfer-Encoding'):
            return
        remaining = int(lengths[0])
        if remaining > 262144:
            return
        self.connection.settimeout(0.25)
        try:
            while remaining:
                chunk = self.rfile.read(min(remaining, 8192))
                if not chunk:
                    break
                remaining -= len(chunk)
        except (OSError, TimeoutError):
            pass
        finally:
            self.connection.settimeout(10)

    def reply(self, status, value, content_type="application/json; charset=utf-8", attachment=False, cookie=None):
        data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="research-delivery.zip"')
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(data)

    def check_request(self, mutate=False, csrf=None):
        port = self.server.server_address[1]
        hosts = (f"127.0.0.1:{port}", f"localhost:{port}")
        require(len(self.headers.get_all("Host", [])) == 1 and self.headers.get("Host") in hosts, "FORBIDDEN")
        origin = self.headers.get("Origin")
        require(len(self.headers.get_all("Origin", [])) <= 1, "FORBIDDEN")
        require(origin is None or origin in ("http://" + host for host in hosts), "FORBIDDEN")
        require(self.headers.get("Sec-Fetch-Site") != "cross-site", "FORBIDDEN")
        if mutate:
            token = self.headers.get("X-CSRF-Token", "")
            require(len(self.headers.get_all("X-CSRF-Token", [])) == 1 and token.isascii(), "FORBIDDEN")
            require(origin is not None and secrets.compare_digest(token, csrf or self.server.csrf), "FORBIDDEN")
            require(self.headers.get("Content-Type", "").split(";")[0] == "application/json")
            require(not self.headers.get("Transfer-Encoding"))
            require(len(self.headers.get_all("Content-Length", [])) == 1)

    def session_token(self):
        headers = self.headers.get_all('Cookie', [])
        if len(headers) != 1 or headers[0].count('cp_session=') != 1:
            return None
        try:
            cookie = SimpleCookie()
            cookie.load(headers[0])
            token = cookie['cp_session'].value
            return token if re.fullmatch(r'[A-Za-z0-9_-]{40,128}', token) else None
        except (KeyError, ValueError):
            return None

    def secure_actor(self):
        token = self.session_token()
        actor = self.server.service.auth.session(token) if token else None
        require(actor is not None, 'UNAUTHENTICATED')
        return actor

    def secure_mutation(self, path, payload, actor):
        service = self.server.service
        auth = service.auth
        identity = actor['user_id']
        if path == '/api/library/import':
            auth.require_role(actor, 'researcher')
            result = service.library.import_text(payload, actor=identity, bind_owner=True)
            return 200, result
        if path == '/api/library/search':
            auth.require_role(actor, 'researcher', 'admin')
            require(type(payload) is dict and set(payload) == {'query', 'document_ids', 'top_k'}, 'INPUT_INVALID')
            require(type(payload['document_ids']) is list, 'INPUT_INVALID')
            require(all(type(value) is str and re.fullmatch('doc-[a-f0-9]{32}', value)
                        for value in payload['document_ids']), 'INPUT_INVALID')
            visible = auth.visible_documents(actor)
            require(set(payload['document_ids']) <= visible, 'NOT_FOUND')
            if not visible:
                # Library.search treats [] as all, so empty private scope must short-circuit.
                require(type(payload['query']) is str and len(payload['query']) <= 200 and
                        type(payload['top_k']) is int and 1 <= payload['top_k'] <= 20, 'INPUT_INVALID')
                return 200, {'mode': 'local-lexical', 'query': payload['query'].strip(),
                             'results': [], 'searched_chunks': 0, 'generated_answer': False}
            return 200, service.library.search({**payload, 'document_ids': payload['document_ids'] or sorted(visible)})
        if path == '/api/projects':
            auth.require_role(actor, 'researcher')
            require(type(payload) is dict and set(payload) ==
                    {'request_id', 'title', 'question', 'constraints', 'version_ids', 'confirmed', 'reviewer_id'}, 'INPUT_INVALID')
            reviewer_id = payload['reviewer_id']
            require(type(reviewer_id) is str and any(u['user_id'] == reviewer_id for u in auth.users('reviewer')), 'ACCESS_DENIED')
            require(type(payload['version_ids']) is list, 'INPUT_INVALID')
            for version in payload['version_ids']:
                require(type(version) is str and re.fullmatch('ver-[a-f0-9]{64}', version), 'INPUT_INVALID')
                auth.version_access(version, actor)
                item = service.library.get(version)
                auth.document_owner(item['document_id'], actor)
            result = service.projects.create({k: v for k, v in payload.items() if k != 'reviewer_id'},
                                             actor=identity, auth=auth, owner=actor, reviewer_id=reviewer_id)
            return 201, result
        match = re.fullmatch(r'/api/projects/(project-[a-f0-9]{32})/tasks', path)
        if match:
            auth.project(match.group(1), actor, owner=True)
            return 202, service.create_project_task(match.group(1), payload, actor=identity)
        match = re.fullmatch(r'/api/tasks/(task-[a-f0-9]{32})/revisions', path)
        if match:
            auth.task(match.group(1), actor, owner=True)
            return 202, service.revise(match.group(1), payload, actor=identity)
        match = re.fullmatch(r'/api/projects/(project-[a-f0-9]{32})/(search|evidence)', path)
        if match:
            auth.project(match.group(1), actor)
            method = service.projects.search if match.group(2) == 'search' else service.projects.evidence
            return 200, method(match.group(1), payload)
        match = re.fullmatch(r'/api/tasks/(task-[a-f0-9]{32})/(actions|archive)', path)
        if match:
            task, operation = match.groups()
            if operation == 'archive':
                auth.task(task, actor, owner=True)
                return 200, service.archive(task, payload, actor=identity)
            require(type(payload) is dict and type(payload.get('action')) is str, 'INPUT_INVALID')
            if payload['action'] in ('approve', 'reject'):
                auth.task(task, actor, reviewer=True)
            else:
                auth.task(task, actor, owner=True)
            return 202, service.operate(task, payload, actor=identity)
        if path == '/api/tasks':
            raise AppError('ACCESS_DENIED')
        raise AppError('NOT_FOUND')

    def secure_read(self, path, actor):
        service = self.server.service
        auth = service.auth
        if path == '/api/security/audit':
            auth.require_role(actor, 'admin')
            with service.store.transaction() as connection:
                rows = connection.execute('''SELECT a.id,a.created_at,a.user_id,u.username,
                    a.action,a.resource,a.outcome FROM access_audit a
                    LEFT JOIN users u ON u.user_id=a.user_id ORDER BY a.id DESC LIMIT 200''').fetchall()
                return {'events': [dict(row) for row in rows], 'limit': 200}
        if path == '/api/bootstrap':
            return {**service.bootstrap(), 'csrf_token': actor['csrf'],
                    'auth_required': True,
                    'identity': {key: actor[key] for key in ('user_id', 'username', 'role')},
                    'reviewers': auth.users('reviewer') if actor['role'] == 'researcher' else []}
        if path == '/api/tasks':
            visible = auth.visible_projects(actor)
            return {'tasks': [item for item in service.store.list_tasks()
                    if item.get('execution', {}).get('project_id') in visible]}
        if path == '/api/library':
            data = service.library.catalog()
            visible = auth.visible_documents(actor)
            data['documents'] = [item for item in data['documents'] if item['document_id'] in visible]
            data['events'] = [item for item in data['events'] if item['document_id'] in visible]
            data['version_count'] = sum(len(item['versions']) for item in data['documents'])
            return data
        if path == '/api/projects':
            visible = auth.visible_projects(actor)
            return {'projects': [item for item in service.projects.list() if item['project_id'] in visible]}
        match = re.fullmatch(r'/api/projects/(project-[a-f0-9]{32})', path)
        if match:
            auth.project(match.group(1), actor)
            return service.projects.get(match.group(1))
        match = re.fullmatch(r'/api/library/versions/(ver-[a-f0-9]{64})', path)
        if match:
            auth.version_access(match.group(1), actor)
            return service.library.get(match.group(1))
        match = re.fullmatch(r'/api/tasks/(task-[a-f0-9]{32})(/download)?', path)
        if match:
            auth.task(match.group(1), actor)
            return service.download(match.group(1)) if match.group(2) else service.detail(match.group(1))
        if path == '/api/knowledge':
            return service.knowledge()
        if path == '/api/evaluations':
            return service.evaluations()
        raise AppError('NOT_FOUND')

    def dispatch(self, mutate=False):
        self._body_read = False
        self.actor = None
        path = self.path.split('?', 1)[0]
        try:
            secure = self.server.service.auth_required
            if secure:
                self.check_request(False)
                if path == '/api/auth/session' and not mutate:
                    token = self.session_token()
                    actor = self.server.service.auth.session(token) if token else None
                    result = {'auth_required': True, 'authenticated': bool(actor),
                              'login_csrf': self.server.csrf if not actor else None}
                    if actor:
                        result.update(identity={key: actor[key] for key in ('user_id', 'username', 'role')}, csrf_token=actor['csrf'])
                    return self.reply(200, result)
                if path == '/api/auth/login' and mutate:
                    self.check_request(True)
                    length = self.headers.get('Content-Length', '')
                    require(length.isdigit() and 0 < int(length) <= 8192)
                    payload = decode(self.rfile.read(int(length)))
                    self._body_read = True
                    require(type(payload) is dict and set(payload) == {'username', 'password'}, 'INPUT_INVALID')
                    token, actor = self.server.service.auth.login(payload['username'], payload['password'])
                    return self.reply(200, {'authenticated': True,
                        'identity': {key: actor[key] for key in ('user_id', 'username', 'role')}},
                        cookie=f'cp_session={token}; HttpOnly; SameSite=Strict; Path=/')
                if path in ASSETS or path == '/favicon.ico':
                    if mutate:
                        raise AppError('NOT_FOUND')
                else:
                    self.actor = self.secure_actor()
                    if mutate:
                        self.check_request(True, self.actor['csrf'])
                    if path == '/api/auth/logout' and mutate:
                        length = self.headers.get('Content-Length', '')
                        require(length.isdigit() and 0 < int(length) <= 8192 and
                                decode(self.rfile.read(int(length))) == {}, 'INPUT_INVALID')
                        self._body_read = True
                        self.server.service.auth.logout(self.session_token(), self.actor)
                        return self.reply(200, {'authenticated': False},
                            cookie='cp_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            else:
                self.check_request(mutate)
                if path == '/api/auth/session' and not mutate:
                    return self.reply(200, {'auth_required': False, 'authenticated': True})
            if mutate:
                length = self.headers.get("Content-Length", "")
                maximum = 131072 if path == "/api/library/import" else 8192
                require(length.isdigit() and 0 < int(length) <= maximum)
                raw = self.rfile.read(int(length))
                self._body_read = True
                payload = decode(raw)
                if secure:
                    status, value = self.secure_mutation(path, payload, self.actor)
                    self.server.service.auth.audit(self.actor, 'http_post', path, 'allowed')
                    return self.reply(status, value)
                if path == "/api/library/import":
                    return self.reply(200, self.server.service.library.import_text(payload))
                if path == "/api/library/search":
                    return self.reply(200, self.server.service.library.search(payload))
                if path == "/api/projects":
                    return self.reply(201, self.server.service.projects.create(payload))
                match = re.fullmatch(r'/api/projects/(project-[a-f0-9]{32})/tasks', path)
                if match:
                    return self.reply(202, self.server.service.create_project_task(match.group(1), payload))
                match = re.fullmatch(r'/api/tasks/(task-[a-f0-9]{32})/revisions', path)
                if match:
                    return self.reply(202, self.server.service.revise(match.group(1), payload))
                match = re.fullmatch(r"/api/projects/(project-[a-f0-9]{32})/(search|evidence)", path)
                if match:
                    project, action = match.groups()
                    method = self.server.service.projects.search if action == 'search' else self.server.service.projects.evidence
                    return self.reply(200, method(project, payload))
                if path == "/api/tasks":
                    return self.reply(202, self.server.service.create(payload))
                match = re.fullmatch(r"/api/tasks/(task-[a-f0-9]{32})/(actions|archive)", path)
                if match:
                    task, operation = match.groups()
                    value = self.server.service.operate(task, payload) if operation == "actions" else self.server.service.archive(task, payload)
                    return self.reply(202 if operation == "actions" else 200, value)
                raise AppError("NOT_FOUND")
            if path in ASSETS:
                file, mime = ASSETS[path]
                return self.reply(200, (APP / "web" / file).read_bytes(), mime)
            if path == "/favicon.ico":
                return self.reply(204, b"", "image/x-icon")
            if secure:
                value = self.secure_read(path, self.actor)
                if path.endswith('/download'):
                    self.server.service.auth.audit(self.actor, 'download', path, 'allowed')
                    return self.reply(200, value, 'application/zip', True)
                return self.reply(200, value)
            if path == "/api/bootstrap":
                return self.reply(200, {**self.server.service.bootstrap(), "csrf_token": self.server.csrf})
            if path == "/api/tasks":
                return self.reply(200, {"tasks": self.server.service.store.list_tasks()})
            if path == "/api/library":
                return self.reply(200, self.server.service.library.catalog())
            if path == "/api/projects":
                return self.reply(200, {"projects": self.server.service.projects.list()})
            match = re.fullmatch(r"/api/projects/(project-[a-f0-9]{32})", path)
            if match:
                return self.reply(200, self.server.service.projects.get(match.group(1)))
            match = re.fullmatch(r"/api/library/versions/(ver-[a-f0-9]{64})", path)
            if match:
                return self.reply(200, self.server.service.library.get(match.group(1)))
            if path == "/api/knowledge":
                return self.reply(200, self.server.service.knowledge())
            if path == "/api/evaluations":
                return self.reply(200, self.server.service.evaluations())
            match = re.fullmatch(r"/api/tasks/(task-[a-f0-9]{32})(/download)?", path)
            if match:
                task, download = match.groups()
                if download:
                    return self.reply(200, self.server.service.download(task), "application/zip", True)
                return self.reply(200, self.server.service.detail(task))
            raise AppError("NOT_FOUND")
        except AppError as error:
            self.drain_rejected_body()
            if self.server.service.auth_required and path.startswith('/api/'):
                self.server.service.auth.audit(self.actor, 'http_' + ('post' if mutate else 'get'), path, error.code)
            self.reply(error.status, {"error": {"code": error.code, "message": error.message}})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            self.reply(500, {"error": {"code": "INTERNAL_ERROR", "message": "处理未完成，请刷新页面查看任务状态。"}})

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch(True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--state-dir", type=str, default=str(APP / ".runtime"))
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument('--auth-required', action='store_true', help='Use a new identity-bound state directory')
    args = parser.parse_args()
    require(0 <= args.port <= 65535)
    service = Service(args.state_dir, auth_required=args.auth_required)
    try:
        if args.auth_required:
            require(service.auth.has_admin(), 'STATE_UNSAFE')
        with Server(args.port, service) as server:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            print(json.dumps({"url": url, "mode": "scripted-offline", "real_model_calls": 0}), flush=True)
            if args.open_browser:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        service.close()


if __name__ == "__main__":
    try:
        main()
    except (AppError, OSError):
        print('{"error":"STARTUP_FAILED","message":"检查端口、状态目录和项目运行环境；不要关闭其他已有服务。"}')
        sys.exit(1)
