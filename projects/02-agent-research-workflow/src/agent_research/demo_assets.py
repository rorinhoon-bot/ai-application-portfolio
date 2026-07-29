"""Deterministic, dependency-free SVG assets for the offline portfolio demo."""

from __future__ import annotations

from html import escape


TERMINAL_LINE_COUNT = 8


def _text(
    *,
    x: int,
    y: int,
    value: str,
    css_class: str,
    anchor: str | None = None,
) -> str:
    anchor_attr = f' text-anchor="{anchor}"' if anchor is not None else ""
    return (
        f'<text x="{x}" y="{y}" class="{css_class}"{anchor_attr}>'
        f"{escape(value)}</text>"
    )


def render_terminal_demo_svg(transcript: str) -> str:
    """Render exact run_demo.py terminal output as an accessible SVG."""

    lines = transcript.rstrip("\n").splitlines()
    if len(lines) != TERMINAL_LINE_COUNT:
        raise ValueError("DEMO_TRANSCRIPT_LINE_COUNT_MISMATCH")
    if not lines[0].startswith("P2 离线演示"):
        raise ValueError("DEMO_TRANSCRIPT_HEADER_MISMATCH")
    status_classes = {
        "[1]": "line human",
        "[2]": "line success",
        "[3]": "line failure",
        "[4]": "line observed",
    }
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 1500 780" role="img" '
        'aria-labelledby="terminal-title terminal-desc">',
        "<title id=\"terminal-title\">P2 离线演示终端截图</title>",
        (
            '<desc id="terminal-desc">真实离线演示输出，展示需求暂停、'
            "成功导出、证据不足停止和节点观测。</desc>"
        ),
        "<style>",
        (
            ".canvas{fill:#08111f}.window{fill:#101827;stroke:#334155;"
            "stroke-width:2}.bar{fill:#172033}.dot-red{fill:#fb7185}"
            ".dot-yellow{fill:#fbbf24}.dot-green{fill:#4ade80}"
            ".chrome{font:500 18px 'Cascadia Mono','Microsoft YaHei UI',"
            "monospace;fill:#94a3b8}.command{font:500 21px "
            "'Cascadia Mono','Microsoft YaHei UI',monospace;fill:#e2e8f0}"
            ".line{font:500 21px 'Cascadia Mono','Microsoft YaHei UI',"
            "monospace;fill:#cbd5e1}.human{fill:#fbbf24}"
            ".success{fill:#4ade80}.failure{fill:#fb7185}"
            ".observed{fill:#60a5fa}.footer{font:400 17px "
            "'Cascadia Mono','Microsoft YaHei UI',monospace;fill:#64748b}"
        ),
        "</style>",
        '<rect class="canvas" width="1500" height="780"/>',
        '<rect class="window" x="35" y="35" width="1430" height="710" rx="18"/>',
        '<path class="bar" d="M53 35h1394a18 18 0 0 1 18 18v55H35V53a18 18 0 0 1 18-18z"/>',
        '<circle class="dot-red" cx="76" cy="72" r="9"/>',
        '<circle class="dot-yellow" cx="108" cy="72" r="9"/>',
        '<circle class="dot-green" cx="140" cy="72" r="9"/>',
        _text(
            x=750,
            y=79,
            value="PowerShell · P2 offline demo",
            css_class="chrome",
            anchor="middle",
        ),
        _text(
            x=70,
            y=145,
            value=(
                "PS> .\\.venv\\Scripts\\python.exe "
                "scripts\\run_demo.py"
            ),
            css_class="command",
        ),
    ]
    start_y = 205
    for index, line in enumerate(lines):
        prefix = line[:3]
        css_class = status_classes.get(prefix, "line")
        parts.append(
            _text(
                x=70,
                y=start_y + index * 52,
                value=line,
                css_class=css_class,
            )
        )
    parts.extend(
        (
            _text(
                x=70,
                y=704,
                value=(
                    "verified: offline-demo-v1 · deterministic · "
                    "network=false · model_api=false"
                ),
                css_class="footer",
            ),
            "</svg>",
        )
    )
    return "\n".join(parts) + "\n"


def _node(
    *,
    x: int,
    y: int,
    title: str,
    subtitle: str,
    kind: str = "normal",
    node_id: str,
) -> str:
    return "\n".join(
        (
            f'<g class="node {kind}" data-node="{escape(node_id)}">',
            f'<rect x="{x}" y="{y}" width="500" height="72" rx="14"/>',
            _text(
                x=x + 250,
                y=y + 30,
                value=title,
                css_class="node-title",
                anchor="middle",
            ),
            _text(
                x=x + 250,
                y=y + 55,
                value=subtitle,
                css_class="node-subtitle",
                anchor="middle",
            ),
            "</g>",
        )
    )


def _callout(
    *,
    x: int,
    y: int,
    title: str,
    subtitle: str,
    kind: str,
    callout_id: str,
) -> str:
    return "\n".join(
        (
            f'<g class="callout {kind}" data-callout="{escape(callout_id)}">',
            f'<rect x="{x}" y="{y}" width="350" height="76" rx="12"/>',
            _text(
                x=x + 175,
                y=y + 31,
                value=title,
                css_class="callout-title",
                anchor="middle",
            ),
            _text(
                x=x + 175,
                y=y + 56,
                value=subtitle,
                css_class="callout-subtitle",
                anchor="middle",
            ),
            "</g>",
        )
    )


def render_workflow_overview_svg() -> str:
    """Render simplified graph with HITL gates, limits, and stable exits."""

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 1600 1020" role="img" '
        'aria-labelledby="workflow-title workflow-desc">',
        "<title id=\"workflow-title\">LangGraph 研究报告工作流</title>",
        (
            '<desc id="workflow-desc">从需求校验到幂等导出的显式状态图，'
            "包含两个人工暂停点、有限重试、证据不足停止和稳定终态。</desc>"
        ),
        "<defs>",
        (
            '<marker id="arrow" markerWidth="10" markerHeight="10" '
            'refX="8" refY="5" orient="auto">'
            '<path d="M0 0L10 5L0 10z" fill="#64748b"/></marker>'
        ),
        "</defs>",
        "<style>",
        (
            ".canvas{fill:#f8fafc}.title{font:500 32px "
            "'Microsoft YaHei UI',sans-serif;fill:#0f172a}"
            ".subtitle{font:400 18px 'Microsoft YaHei UI',sans-serif;"
            "fill:#475569}.edge{fill:none;stroke:#64748b;stroke-width:2;"
            "marker-end:url(#arrow)}.branch{fill:none;stroke:#94a3b8;"
            "stroke-width:2;stroke-dasharray:7 7;marker-end:url(#arrow)}"
            ".edge-label{font:400 16px 'Microsoft YaHei UI',sans-serif;"
            "fill:#475569}.node rect{fill:#e0f2fe;stroke:#0284c7;"
            "stroke-width:2}.node.human rect{fill:#fef3c7;stroke:#d97706}"
            ".node.success rect{fill:#dcfce7;stroke:#16a34a}"
            ".node-title{font:500 20px 'Microsoft YaHei UI',sans-serif;"
            "fill:#0f172a}.node-subtitle{font:400 15px "
            "'Microsoft YaHei UI',sans-serif;fill:#475569}"
            ".callout rect{fill:#f1f5f9;stroke:#94a3b8;stroke-width:2}"
            ".callout.failure rect{fill:#fee2e2;stroke:#dc2626}"
            ".callout.human rect{fill:#fff7ed;stroke:#ea580c}"
            ".callout-title{font:500 18px 'Microsoft YaHei UI',sans-serif;"
            "fill:#0f172a}.callout-subtitle{font:400 14px "
            "'Microsoft YaHei UI',sans-serif;fill:#475569}"
            ".legend{font:400 15px 'Microsoft YaHei UI',sans-serif;"
            "fill:#64748b}"
        ),
        "</style>",
        '<rect class="canvas" width="1600" height="1020"/>',
        _text(
            x=800,
            y=48,
            value="LangGraph 研究报告工作流",
            css_class="title",
            anchor="middle",
        ),
        _text(
            x=800,
            y=78,
            value="显式状态 · 两个人工门 · 有限循环 · checkpoint · 幂等导出",
            css_class="subtitle",
            anchor="middle",
        ),
        # Main edges.
        '<path class="edge" d="M800 166V190"/>',
        '<path class="edge" d="M800 262V286"/>',
        '<path class="edge" d="M800 358V382"/>',
        '<path class="edge" d="M800 454V478"/>',
        '<path class="edge" d="M800 550V574"/>',
        '<path class="edge" d="M800 646V670"/>',
        '<path class="edge" d="M800 742V766"/>',
        '<path class="edge" d="M800 838V872"/>',
        # Branches and loops.
        '<path class="branch" d="M550 226H430"/>',
        '<path class="branch" d="M1050 418H1170"/>',
        '<path class="branch" d="M1345 456V478H1050"/>',
        '<path class="branch" d="M550 514H430"/>',
        '<path class="branch" d="M1050 610H1170"/>',
        '<path class="branch" d="M1345 648V670H1050"/>',
        '<path class="branch" d="M550 706H430"/>',
        _text(
            x=466,
            y=213,
            value="缺字段",
            css_class="edge-label",
            anchor="middle",
        ),
        _text(
            x=1110,
            y=405,
            value="瞬时错误",
            css_class="edge-label",
            anchor="middle",
        ),
        _text(
            x=466,
            y=501,
            value="第 2 轮仍不足",
            css_class="edge-label",
            anchor="middle",
        ),
        _text(
            x=1110,
            y=597,
            value="发现问题",
            css_class="edge-label",
            anchor="middle",
        ),
        _text(
            x=466,
            y=693,
            value="拒绝 / 取消",
            css_class="edge-label",
            anchor="middle",
        ),
        _node(
            x=550,
            y=94,
            title="1. 需求校验",
            subtitle="候选、评价维度、范围完整性",
            node_id="validate-request",
        ),
        _node(
            x=550,
            y=190,
            title="2. Human-in-the-loop：需求确认",
            subtitle="先写 checkpoint，再正常暂停；决定绑定 revision/hash",
            kind="human",
            node_id="requirements-human-gate",
        ),
        _node(
            x=550,
            y=286,
            title="3. 研究规划",
            subtitle="固定范围与调用预算，不扩大权限",
            node_id="plan-research",
        ),
        _node(
            x=550,
            y=382,
            title="4. 只读 Tool Calling",
            subtitle="名称 allowlist + Schema + 业务作用域；最多重试 2 次",
            node_id="tool-calling",
        ),
        _node(
            x=550,
            y=478,
            title="5. 证据充分性门",
            subtitle="最多检索 2 轮；不能用常识或模型推断补证据",
            node_id="evidence-gate",
        ),
        _node(
            x=550,
            y=574,
            title="6. 结构化写作与审校",
            subtitle="程序绑定引用；自动修改最多 2 次",
            node_id="draft-and-review",
        ),
        _node(
            x=550,
            y=670,
            title="7. Human-in-the-loop：报告确认",
            subtitle="批准绑定 report revision/hash；旧批准失效",
            kind="human",
            node_id="report-human-gate",
        ),
        _node(
            x=550,
            y=766,
            title="8. 安全幂等导出",
            subtitle="内容寻址 Markdown；不覆盖；重复导出 UNCHANGED",
            node_id="safe-export",
        ),
        _node(
            x=550,
            y=872,
            title="COMPLETED",
            subtitle="已批准报告与 artifact_id 保持绑定",
            kind="success",
            node_id="completed",
        ),
        _callout(
            x=55,
            y=188,
            title="NEEDS_HUMAN",
            subtitle="等待人工是正常状态，不是失败",
            kind="human",
            callout_id="needs-human",
        ),
        _callout(
            x=1195,
            y=380,
            title="retry_tool",
            subtitle="同一逻辑调用键；attempt 写入 checkpoint",
            kind="normal",
            callout_id="tool-retry",
        ),
        _callout(
            x=55,
            y=476,
            title="FAILED",
            subtitle="evidence-insufficient；不写报告",
            kind="failure",
            callout_id="evidence-failed",
        ),
        _callout(
            x=1195,
            y=572,
            title="revise_report",
            subtitle="按持久化轮次修改，再回到审校",
            kind="normal",
            callout_id="review-loop",
        ),
        _callout(
            x=55,
            y=668,
            title="稳定人工终态",
            subtitle="REPORT_REJECTED / REPORT_CANCELLED",
            kind="failure",
            callout_id="human-terminal",
        ),
        _text(
            x=800,
            y=987,
            value=(
                "离线确定性夹具：12/12 案例通过 · 144 项测试 · "
                "network=false · model_api=false"
            ),
            css_class="legend",
            anchor="middle",
        ),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"
