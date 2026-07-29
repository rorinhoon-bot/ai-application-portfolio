"""Render a deterministic portfolio image from the saved MiMo smoke report."""

from __future__ import annotations

import json
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "data" / "mimo-smoke-report.json"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "images" / "cli-demo.png"

WIDTH = 1500
HEIGHT = 980
PADDING = 58
BACKGROUND = "#0d1117"
PANEL = "#161b22"
TEXT = "#e6edf3"
MUTED = "#8b949e"
GREEN = "#3fb950"
BLUE = "#58a6ff"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _wrapped(value: str, width: int = 70) -> list[str]:
    return textwrap.wrap(
        value,
        width=width,
        replace_whitespace=False,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]


def main() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    answer = report["answer"]
    citation = answer["citations"][0]

    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    title_font = _font(30)
    body_font = _font(23)
    small_font = _font(20)

    draw.rounded_rectangle(
        (28, 28, WIDTH - 28, HEIGHT - 28),
        radius=18,
        fill=PANEL,
        outline="#30363d",
        width=2,
    )
    for index, color in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        x = 60 + index * 34
        draw.ellipse((x, 58, x + 18, 76), fill=color)

    y = 105
    draw.text(
        (PADDING, y),
        "P1 · 带引用的知识库问答",
        font=title_font,
        fill=TEXT,
    )
    y += 55
    draw.text(
        (PADDING, y),
        "已保存真实 MiMo smoke report 的可复核展示",
        font=small_font,
        fill=MUTED,
    )
    y += 60

    command = (
        'python -m cited_rag ask --question "Python 3.14 中，使用 venv '
        '创建虚拟环境应运行什么命令？" --python-version 3.14'
    )
    for index, line in enumerate(_wrapped(command, 76)):
        prefix = "$ " if index == 0 else "  "
        draw.text(
            (PADDING, y),
            prefix + line,
            font=body_font,
            fill=GREEN,
        )
        y += 37
    y += 24

    fields = (
        ('"status"', f'"{answer["status"]}"'),
        ('"answer"', answer["answer"].replace("\n", " ")),
        ('"python_version"', f'"{citation["python_version"]}"'),
        ('"documentation_release"', f'"{citation["documentation_release"]}"'),
        ('"citation_url"', citation["citation_url"]),
        ('"chunk_id"', citation["chunk_id"]),
        ('"total_tokens"', str(answer["total_tokens"])),
    )
    draw.text((PADDING, y), "{", font=body_font, fill=TEXT)
    y += 37
    for key, value in fields:
        lines = _wrapped(value, 76)
        draw.text(
            (PADDING + 28, y),
            f"{key}: ",
            font=body_font,
            fill=BLUE,
        )
        key_width = draw.textlength(f"{key}: ", font=body_font)
        draw.text(
            (PADDING + 28 + key_width, y),
            lines[0],
            font=body_font,
            fill=TEXT,
        )
        y += 35
        for line in lines[1:]:
            draw.text(
                (PADDING + 28, y),
                line,
                font=body_font,
                fill=TEXT,
            )
            y += 35
        y += 4
    draw.text((PADDING, y), "}", font=body_font, fill=TEXT)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_PATH, format="PNG", optimize=True)
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
