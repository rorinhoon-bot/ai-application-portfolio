"""Application orchestration. No model or workflow imported in this process."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import threading

from domain import APP, REPO, AppError, DEFAULT_QUESTION, fields, identifier, require, safe_path, text
from engine import OfflineEngine, FrozenEngine
from frozen_contract import prepare
from projects import project_text
from store import Store
from library import Library
from projects import ResearchProjects
from auth import AuthManager


class StateLock:
    def __init__(self, root, auth_required=False):
        root = safe_path(root, directory=True)
        root.mkdir(parents=True, exist_ok=True)
        marker = root / "workspace.json"
        schema = 'course-platform-state-v2-auth' if auth_required else 'course-platform-state-v1'
        if not marker.exists():
            require(not list(root.iterdir()), "STATE_UNSAFE")
            marker.write_text(json.dumps({'schema_version': schema}) + '\n', encoding="utf-8")
        require(json.loads(safe_path(marker).read_text(encoding="utf-8")) ==
                {"schema_version": schema}, "STATE_UNSAFE")
        self.stream = safe_path(root / "service.lock").open("a+b")
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise AppError("STATE_BUSY") from None

    def close(self):
        self.stream.close()


class Service:
    def __init__(self, root, engine=None, *, auth_required=False):
        self.root = safe_path(root, directory=True)
        self.auth_required = auth_required
        self.lock = StateLock(self.root, auth_required)
        try:
            self.store = Store(self.root)
            self.library = Library(self.store)
            self.projects = ResearchProjects(self.store)
            self.auth = AuthManager(self.store) if auth_required else None
            self.store.interrupt_pending()
            self.engine = engine or OfflineEngine()
            self.frozen_engine = FrozenEngine()
            self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="course-work")
            self.catalog_lock = threading.Lock()
            self.catalog_cache = None
        except BaseException:
            self.lock.close()
            raise

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.lock.close()

    def bootstrap(self):
        return {"name": "研据工作台", "version": "1.0-offline", "mode": "scripted-offline",
                "default_question": DEFAULT_QUESTION, "default_title": "AI 研究交付方案对比",
                "candidates": ["graph-plan", "chain-plan"],
                "dimensions": ["tool-calling", "human-approval", "recovery"],
                "limits": {"tasks": 200, "queue": 8, "real_model_calls": 0},
                "scope": "固定示例使用两个原创方案；研究项目可冻结2—4份本机资料。两种模式都只使用离线脚本模型。",
                "quality": "P2真实模型内容验收未通过；本机工程测试不能替代内容质量评价。"}

    def create(self, payload, actor='local-browser'):
        fields(payload, "request_id title question")
        request = identifier(payload["request_id"])
        value = {"title": text(payload["title"], 2, 80), "question": text(payload["question"], 10, 500)}
        task, new = self.store.reserve(request, "create", value, actor=actor)
        if new:
            self.pool.submit(self._run, task, request, "create", value)
        return self.store.get(task)

    def operate(self, task, payload, actor='local-browser'):
        identifier(task, "task-")
        fields(payload, "request_id action expected_hash note")
        request = identifier(payload["request_id"])
        require(payload["action"] in ("approve", "reject", "cancel", "recover"))
        action = payload["action"]
        require(type(payload["expected_hash"]) is str and
                (re.fullmatch(r"[a-f0-9]{64}", payload["expected_hash"]) or
                 action == "recover" and payload["expected_hash"] == ""))
        value = {"expected_hash": payload["expected_hash"], "note": text(payload["note"], 4, 1000)}
        _, new = self.store.reserve(request, action, value, task=task, actor=actor)
        if new:
            self.pool.submit(self._run, task, request, action, value)
        return self.store.get(task)

    def create_project_task(self, project, payload, actor='local-browser'):
        request, snapshot = prepare(self.projects, project, payload)
        value = {'title': snapshot['project_title'], 'question': snapshot['question'], 'execution': snapshot}
        task, new = self.store.reserve(request, 'create', value, actor=actor)
        if new:
            self.pool.submit(self._run, task, request, 'create', value)
        return self.store.get(task)

    def revise(self, task, payload, actor='local-browser'):
        identifier(task, 'task-')
        fields(payload, 'request_id expected_hash summary limitations note confirmed')
        require(payload['confirmed'] is True and self.store.execution(task) is not None, 'REVISION_INVALID')
        request = identifier(payload['request_id'])
        require(type(payload['expected_hash']) is str and re.fullmatch('[a-f0-9]{64}', payload['expected_hash']))
        require(type(payload['limitations']) is list and 1 <= len(payload['limitations']) <= 8)
        value = {'expected_hash': payload['expected_hash'], 'summary': project_text(payload['summary'], 10, 800),
                 'limitations': [project_text(v, 2, 200) for v in payload['limitations']],
                 'note': project_text(payload['note'], 4, 300)}
        _, new = self.store.reserve(request, 'revise', value, task=task, actor=actor)
        if new:
            self.pool.submit(self._run, task, request, 'revise', value)
        return self.store.get(task)

    def _run(self, task, request, action, payload):
        try:
            self.store.running(request)
            root = self.root / "tasks" / task
            question = self.store.get(task)["question"]
            snapshot = self.store.execution(task)
            if snapshot:
                result = self.frozen_engine.call(action, root, {'snapshot': snapshot, 'request_id': request, 'payload': payload if action != 'create' else {}})
            elif action == "create":
                result = self.engine.call("create", root, {"question": question})
            else:
                result = self.engine.call("operate", root,
                                          {"action": action, "expected_hash": payload["expected_hash"], "question": question})
            state = result.get("state")
            require(type(state) is dict and type(state.get("status")) is str and state["status"], "ENGINE_FAILED")
            self.store.finish(task, request, state=state)
        except AppError as error:
            self.store.finish(task, request, error=error.code)
        except Exception:
            self.store.finish(task, request, error="ENGINE_FAILED")

    def archive(self, task, payload, actor='local-browser'):
        identifier(task, "task-")
        fields(payload, "archived")
        require(type(payload["archived"]) is bool)
        self.store.archive(task, payload["archived"], actor=actor)
        return self.store.get(task)

    def detail(self, task):
        return self.store.get(identifier(task, "task-"))

    def download(self, task):
        item = self.detail(task)
        require(not item["busy"], "TASK_BUSY")
        require(item["status"] == "COMPLETED", "NOT_COMPLETED")
        snapshot = self.store.execution(task)
        result = (self.frozen_engine.call('export', self.root / 'tasks' / task,
                  {'snapshot': snapshot, 'request_id': '0' * 32, 'payload': {}}) if snapshot else
                  self.engine.call("export", self.root / "tasks" / task, {}))
        require(result.get("verification", {}).get("bundle_consistent") is True, "ENGINE_FAILED")
        try:
            return base64.b64decode(result["zip_base64"], validate=True)
        except (ValueError, KeyError):
            raise AppError("ENGINE_FAILED") from None

    def knowledge(self):
        with self.catalog_lock:
            if self.catalog_cache is None:
                result = self.engine.call("catalog", self.root / "catalog", {})
                require(type(result.get("records")) is list, "ENGINE_FAILED")
                self.catalog_cache = result
            return self.catalog_cache

    def evaluations(self):
        result = json.loads((REPO / "docs/integration/publication-results/ready.json").read_text(encoding="utf-8"))
        return {"label": "2026-09-17 发布基线；不是本次任务的内容评分", "results": result["results"],
                "content_quality": "not_accepted", "limits": self.bootstrap()["quality"],
                "provenance": "docs/integration/publication-results/ready.json",
                "current_app": "本课设UI的验收与浏览器证据单独记录在apps/course-platform/docs。"}
