"""Streamlit presentation layer for the cited knowledge-base service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pydantic import ValidationError
import streamlit as st

from cited_rag.errors import CitedRagError
from cited_rag.models import AnswerResult, PythonVersion


class UiApplication(Protocol):
    def answer(
        self,
        *,
        question: str,
        python_version: PythonVersion | None = None,
    ) -> AnswerResult:
        ...


UiApplicationFactory = Callable[[], UiApplication]

_VERSION_OPTIONS: dict[str, PythonVersion | None] = {
    "自动判断": None,
    "Python 3.14": "3.14",
    "Python 3.13": "3.13",
}
_EXAMPLES = (
    (
        "中文 JSON",
        "Python 3.14 使用 json.dumps 输出中文时怎样避免 ASCII 转义？",
        "Python 3.14",
    ),
    (
        "创建虚拟环境",
        "Python 3.14 中，使用 venv 创建虚拟环境应运行什么命令？",
        "Python 3.14",
    ),
    (
        "比较版本",
        "Python 3.13 与 3.14 中，ArgumentParser 默认 prog 有什么不同？",
        "自动判断",
    ),
)
_ERROR_MESSAGES = {
    "RETRIEVAL_INPUT_ERROR": (
        "问题格式无效",
        "请输入1到500个字符，并去除多余首尾空格。",
    ),
    "INDEX_CONSISTENCY_ERROR": (
        "本地索引不可用",
        "请按README恢复或重建固定Qdrant索引。",
    ),
    "RETRIEVAL_ERROR": (
        "检索失败",
        "本地向量检索未完成，请检查索引文件后重试。",
    ),
    "MODEL_TIMEOUT": (
        "模型响应超时",
        "本次请求没有自动重试。请稍后再次提交。",
    ),
    "MODEL_NETWORK_ERROR": (
        "无法连接生成模型",
        "请检查网络和 `.env` 中的MiMo配置。",
    ),
    "MODEL_HTTP_ERROR": (
        "生成模型服务拒绝请求",
        "请检查API Key、账户状态和模型配置。",
    ),
    "INVALID_MODEL_JSON": (
        "模型返回格式无效",
        "系统已拒绝不符合JSON合同的输出，没有展示不可信回答。",
    ),
    "MODEL_OUTPUT_ERROR": (
        "模型回答未通过校验",
        "系统已拒绝缺少正文或引用的结果。",
    ),
    "INVALID_CITATION_ID": (
        "模型引用无效",
        "系统已拒绝不属于本次检索结果的引用。",
    ),
}

_STYLE = """
<style>
    :root {
        --ink: #172033;
        --muted: #64748b;
        --line: #dce3ef;
        --accent: #3157d5;
        --soft: #eef3ff;
    }
    .stApp {
        background:
            radial-gradient(circle at 82% 8%, #e8edff 0, transparent 27rem),
            linear-gradient(180deg, #fbfcff 0%, #f6f8fc 100%);
    }
    .block-container {
        max-width: 1120px;
        padding-top: 2.6rem;
        padding-bottom: 4rem;
    }
    [data-testid="stSidebar"] {
        background: #111a2f;
        color: #edf2ff;
        border-right: 1px solid #263554;
    }
    [data-testid="stSidebar"] * {
        color: #edf2ff;
    }
    .hero-kicker {
        color: #3157d5;
        font-size: .82rem;
        font-weight: 800;
        letter-spacing: .12em;
        text-transform: uppercase;
        margin-bottom: .7rem;
    }
    .hero-title {
        color: var(--ink);
        font-size: clamp(2.25rem, 5vw, 4rem);
        line-height: 1.04;
        letter-spacing: -.045em;
        font-weight: 800;
        margin: 0;
        max-width: 850px;
    }
    .hero-copy {
        color: var(--muted);
        font-size: 1.08rem;
        line-height: 1.75;
        max-width: 780px;
        margin: 1.2rem 0 2rem;
    }
    .trust-strip {
        display: flex;
        flex-wrap: wrap;
        gap: .6rem;
        margin-bottom: 1.4rem;
    }
    .trust-item {
        background: rgba(255,255,255,.85);
        border: 1px solid var(--line);
        border-radius: 999px;
        color: #43516a;
        font-size: .86rem;
        padding: .45rem .75rem;
    }
    .status-pill {
        display: inline-block;
        border-radius: 999px;
        font-size: .78rem;
        font-weight: 800;
        letter-spacing: .08em;
        padding: .35rem .65rem;
        text-transform: uppercase;
        margin-bottom: .7rem;
    }
    .status-answered { background: #dcfce7; color: #166534; }
    .status-refused { background: #f1f5f9; color: #475569; }
    .status-conflict { background: #fef3c7; color: #92400e; }
    div[data-testid="stForm"] {
        background: rgba(255,255,255,.9);
        border: 1px solid var(--line);
        border-radius: 1.15rem;
        padding: 1.1rem 1.25rem 1.3rem;
        box-shadow: 0 18px 50px rgba(31, 48, 92, .08);
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(255,255,255,.78);
        border-color: var(--line);
        border-radius: 1rem;
    }
    .sidebar-brand {
        font-size: 1.35rem;
        font-weight: 800;
        letter-spacing: -.02em;
        margin-bottom: .4rem;
    }
    .sidebar-copy {
        color: #b9c5dd !important;
        font-size: .9rem;
        line-height: 1.65;
    }
</style>
"""


def run_ui(*, application_factory: UiApplicationFactory) -> None:
    """Render one local, read-only question-answering page."""

    st.set_page_config(
        page_title="Python 官方文档问答",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(_STYLE, unsafe_allow_html=True)
    _render_sidebar()
    _render_hero()
    _render_examples()

    with st.form("question_form", border=True):
        question = st.text_area(
            "输入问题",
            key="question_input",
            placeholder=(
                "例如：Python 3.14 使用 json.dumps 输出中文时，"
                "怎样避免 ASCII 转义？"
            ),
            max_chars=500,
            height=118,
        )
        version_label = st.radio(
            "文档范围",
            options=tuple(_VERSION_OPTIONS),
            horizontal=True,
            key="version_scope",
            help="比较3.13与3.14时选择“自动判断”。",
        )
        submitted = st.form_submit_button(
            "检索并生成带引用回答",
            type="primary",
            width="stretch",
            key="submit_question",
        )

    if submitted:
        _submit_question(
            application_factory=application_factory,
            question=question,
            python_version=_VERSION_OPTIONS[version_label],
        )

    error = st.session_state.get("_cited_rag_ui_error")
    result = st.session_state.get("_cited_rag_ui_result")
    if error is not None:
        _render_error(error)
    elif result is not None:
        _render_answer(result)
    else:
        st.info(
            "输入问题后，系统会先检索本地官方文档，"
            "再让MiMo只依据检索证据回答。"
        )


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="sidebar-brand">Cited Python KB</div>'
            '<div class="sidebar-copy">'
            "本地语料 · 本地向量 · 程序绑定引用"
            "</div>",
            unsafe_allow_html=True,
        )
        st.divider()
        st.metric("检索 Recall@5", "86.7%", "基线 +20.0 pp")
        st.metric("引用绑定有效率", "100%")
        st.metric("版本比较人工复核", "3 / 3")
        st.divider()
        st.caption("语料范围")
        st.write("Python 3.14 官方简体中文文档子集")
        st.write("少量 Python 3.13 对照文档")
        st.caption(
            "首版不联网搜索网页；生成模型只接收本次检索到的证据。"
        )


def _render_hero() -> None:
    st.markdown(
        """
        <div class="hero-kicker">P1 · AI Application Portfolio</div>
        <h1 class="hero-title">回答可以生成，<br>引用必须真实。</h1>
        <p class="hero-copy">
            面向 Python 3.13 / 3.14 官方简体中文文档的本地知识库。
            检索证据不足时拒答；URL、版本、章节与摘录全部由程序绑定。
        </p>
        <div class="trust-strip">
            <span class="trust-item">官方 HTML 快照</span>
            <span class="trust-item">BGE 本地 Embedding</span>
            <span class="trust-item">Qdrant 本地索引</span>
            <span class="trust-item">MiMo 证据约束回答</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_examples() -> None:
    st.caption("示例问题")
    columns = st.columns(len(_EXAMPLES))
    for column, (label, question, version) in zip(
        columns,
        _EXAMPLES,
        strict=True,
    ):
        column.button(
            label,
            key=f"example_{label}",
            on_click=_set_example,
            args=(question, version),
            width="stretch",
        )


def _set_example(question: str, version: str) -> None:
    st.session_state["question_input"] = question
    st.session_state["version_scope"] = version
    st.session_state.pop("_cited_rag_ui_result", None)
    st.session_state.pop("_cited_rag_ui_error", None)


def _submit_question(
    *,
    application_factory: UiApplicationFactory,
    question: str,
    python_version: PythonVersion | None,
) -> None:
    normalized_question = question.strip()
    st.session_state.pop("_cited_rag_ui_result", None)
    st.session_state.pop("_cited_rag_ui_error", None)
    if not normalized_question:
        st.session_state["_cited_rag_ui_error"] = {
            "title": "请输入问题",
            "message": "问题不能为空。",
            "code": "RETRIEVAL_INPUT_ERROR",
        }
        return

    try:
        with st.spinner("正在检索本地文档并校验证据…"):
            application = st.session_state.get("_cited_rag_application")
            if application is None:
                application = application_factory()
                st.session_state["_cited_rag_application"] = application
            result = application.answer(
                question=normalized_question,
                python_version=python_version,
            )
    except CitedRagError as error:
        title, message = _ERROR_MESSAGES.get(
            error.code,
            (
                "请求未完成",
                "系统安全停止，没有展示未经验证的回答。",
            ),
        )
        st.session_state["_cited_rag_ui_error"] = {
            "title": title,
            "message": message,
            "code": error.code,
        }
    except (OSError, ValidationError):
        st.session_state["_cited_rag_ui_error"] = {
            "title": "本地配置无效",
            "message": "请检查 `.env`、模型资产和活动索引。",
            "code": "CONFIG_ERROR",
        }
    except Exception:
        st.session_state["_cited_rag_ui_error"] = {
            "title": "应用发生意外错误",
            "message": "错误详情已隐藏，避免泄露密钥或供应商响应。",
            "code": "INTERNAL_ERROR",
        }
    else:
        st.session_state["_cited_rag_ui_result"] = result


def _render_error(error: dict[str, str]) -> None:
    st.error(f"**{error['title']}**\n\n{error['message']}")
    st.caption(f"错误代码：`{error['code']}`")


def _render_answer(result: AnswerResult) -> None:
    status_labels = {
        "answered": "已回答",
        "refused": "证据不足 · 已拒答",
        "conflict": "版本冲突",
    }
    st.divider()
    st.markdown(
        (
            f'<span class="status-pill status-{result.status}">'
            f"{status_labels[result.status]}</span>"
        ),
        unsafe_allow_html=True,
    )
    st.subheader("回答")
    if result.status == "refused":
        st.info(result.answer)
    elif result.status == "conflict":
        st.warning(result.answer)
    else:
        st.markdown(result.answer)

    if result.citations:
        st.subheader(f"引用证据 · {len(result.citations)}")
        for index, citation in enumerate(result.citations, start=1):
            with st.container(border=True):
                header, action = st.columns([4, 1])
                header.markdown(
                    f"**引用 {index} · Python "
                    f"{citation.python_version}**"
                )
                header.caption(
                    f"文档发布版 {citation.documentation_release}"
                    f" · 检索排名 #{citation.rank}"
                )
                action.link_button(
                    "打开原文",
                    str(citation.citation_url),
                    key=f"citation_{citation.chunk_id}",
                    icon=":material/open_in_new:",
                    width="stretch",
                )
                st.caption(" / ".join(citation.section_path))
                st.code(
                    citation.excerpt,
                    language=None,
                    wrap_lines=True,
                )

    with st.expander("运行追踪"):
        trace_a, trace_b, trace_c = st.columns(3)
        trace_a.metric("Prompt tokens", result.prompt_tokens or "—")
        trace_b.metric(
            "Completion tokens",
            result.completion_tokens or "—",
        )
        trace_c.metric("Total tokens", result.total_tokens or "—")
        st.caption("Index ID")
        st.code(str(result.index_id), language=None)
        st.caption("Build ID")
        st.code(str(result.build_id), language=None)
