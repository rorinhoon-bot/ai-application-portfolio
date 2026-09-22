"""Public contracts and stable errors for the local course application."""
import hashlib
import json
from pathlib import Path
import re

APP = Path(__file__).resolve().parent
REPO = APP.parents[1]
INTEGRATION = REPO / "integrations/graduation"
DEFAULT_QUESTION = "比较 graph-plan 与 chain-plan 在工具调用、人工审批和故障恢复方面的设计，说明证据与限制。"
ERRORS = {
    "UNAUTHENTICATED": (401, "请先登录当前工作空间。"),
    "LOGIN_FAILED": (401, "用户名或密码不正确。"),
    "LOGIN_LOCKED": (429, "登录尝试过多，请稍后再试。"),
    "ACCESS_DENIED": (403, "当前身份没有执行此操作的权限。"),
    "EXECUTION_SCOPE": (400, "请选择2—4个不同候选及冻结资料；执行范围最多64段、96KiB正文。"),
    "REVISION_INVALID": (409, "仅能修订待审动态报告，最多2次；请核对当前报告版本。"),
    "PROJECT_LIMIT": (429, "研究项目已达本机200个上限。"),
    "PROJECT_INTEGRITY": (409, "冻结范围或资料校验失败，请保留记录并检查数据。"),
    "PROJECT_EVIDENCE": (409, "证据不属于当前冻结范围，或内容指纹不一致。"),
    "PROJECT_CONFIRMATION": (400, "请确认研究项目输入与资料授权后再创建。"),
    "PROJECT_CONTRACT": (400, "研究项目合同格式不正确，请检查约束和资料版本。"),
    "PROJECT_CONFLICT": (409, "请求标识已用于其他研究项目内容，请重新操作。"),
    "LIBRARY_CONFIRMATION": (400, "请确认资料使用授权后再导入。"),
    "LIBRARY_FILE": (400, "只支持普通文件名的 UTF-8 TXT/Markdown；不能提交路径或隐藏文件。"),
    "LIBRARY_LIMIT": (413, "资料超出容量：正文最多48000字节、128段；资料库最多50份资料、200版本。"),
    "LIBRARY_STALE": (409, "资料版本已改变或来源已存在。请刷新并通过“新增版本”操作。"),
    "LIBRARY_OLD_VERSION": (409, "此内容与历史版本完全相同。请查看历史版本，或提交新的修订内容。"),
    "INPUT_INVALID": (400, "输入格式不正确，请检查必填内容。"),
    "NOT_FOUND": (404, "未找到这个任务或资源。"),
    "FORBIDDEN": (403, "请求来源或会话验证失败，请刷新本机页面。"),
    "TASK_BUSY": (409, "任务正在处理，请等待当前操作完成。"),
    "STALE_APPROVAL": (409, "审批对象已改变，请刷新后重新阅读。"),
    "IDEMPOTENCY_CONFLICT": (409, "请求标识已用于其他内容，请重新操作。"),
    "LIMIT_REACHED": (429, "本机演示容量已达上限，请等待队列完成或使用新的状态目录。"),
    "NOT_COMPLETED": (409, "报告尚未批准交付，暂时不能下载。"),
    "ENGINE_UNAVAILABLE": (503, "项目运行环境不完整，请查看README的环境检查步骤。"),
    "ENGINE_FAILED": (422, "研究执行未完成。可尝试恢复，或复制问题创建新任务。"),
    "ENGINE_TIMEOUT": (504, "研究处理超时，已停止本次工作进程。请检查任务后选择恢复。"),
    "STATE_UNSAFE": (400, "状态目录不符合本机安全要求。"),
    "STATE_BUSY": (409, "这个状态目录已由另一个工作台使用。"),
}


class AppError(ValueError):
    def __init__(self, code):
        self.code = code if code in ERRORS else "ENGINE_FAILED"
        self.status, self.message = ERRORS[self.code]
        super().__init__(self.code)


def require(condition, code="INPUT_INVALID"):
    if not condition:
        raise AppError(code)


def fields(value, names):
    require(type(value) is dict and set(value) == set(names.split()))


def text(value, minimum, maximum):
    require(type(value) is str and minimum <= len(value.strip()) <= maximum and "\x00" not in value)
    return value.strip()


def identifier(value, prefix=""):
    require(type(value) is str and re.fullmatch(prefix + r"[a-f0-9]{32}", value) is not None)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def safe_path(path, *, directory=False):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            require(not part.is_symlink() and not getattr(part.lstat(), "st_file_attributes", 0) & 0x400,
                    "STATE_UNSAFE")
    if path.exists():
        require(path.is_dir() if directory else path.is_file(), "STATE_UNSAFE")
    return path


def decode(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value)
            value[key] = item
        return value
    def invalid(value):
        raise AppError("INPUT_INVALID")
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid, parse_float=invalid)
    except (ValueError, UnicodeError, RecursionError):
        raise AppError("INPUT_INVALID") from None
