"""Deterministic parser for the accepted Python documentation HTML subset."""

from __future__ import annotations

import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag

from cited_rag.errors import DocumentParseError
from cited_rag.models import (
    ContentBlockType,
    ParsedContentBlock,
    ParsedDocument,
)

MAIN_SELECTORS = (
    'main[role="main"]',
    'div.body[role="main"]',
    "div.document div.body",
)
NOISE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "template",
    "nav",
    "footer",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    ".headerlink",
    ".viewcode-link",
    ".related",
    ".sphinxsidebar",
    ".toc-drawer",
    ".mobile-header",
)
HEADING_NAMES = ("h1", "h2", "h3", "h4", "h5", "h6")


class PythonDocsHtmlParser:
    """Parse trusted-shape evidence from an untrusted HTML string."""

    def parse(self, html: str) -> ParsedDocument:
        if not isinstance(html, str) or not html.strip():
            raise DocumentParseError("HTML input is empty")

        soup = BeautifulSoup(html, "html.parser")
        canonical_url = self._extract_canonical_url(soup)
        main = self._find_unique_main(soup)
        self._remove_noise(main)
        self._validate_unique_anchors(main)
        page_title = self._extract_page_title(main)
        blocks, warnings = self._extract_blocks(main)
        if not blocks:
            raise DocumentParseError("main content has no supported body blocks")

        return ParsedDocument(
            page_title=page_title,
            html_canonical_url=canonical_url,
            blocks=tuple(blocks),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _extract_canonical_url(soup: BeautifulSoup) -> str | None:
        canonical_links = soup.select('link[rel~="canonical"]')
        if len(canonical_links) > 1:
            raise DocumentParseError("multiple canonical URLs found")
        if not canonical_links:
            return None

        href = canonical_links[0].get("href")
        if not isinstance(href, str) or not href.strip():
            raise DocumentParseError("canonical URL is empty")
        return href.strip()

    @staticmethod
    def _find_unique_main(soup: BeautifulSoup) -> Tag:
        matches: list[Tag] = []
        for selector in MAIN_SELECTORS:
            for candidate in soup.select(selector):
                if not any(candidate is existing for existing in matches):
                    matches.append(candidate)

        if not matches:
            raise DocumentParseError("main content not found")
        if len(matches) > 1:
            raise DocumentParseError("multiple main content regions found")
        return matches[0]

    @staticmethod
    def _remove_noise(main: Tag) -> None:
        for selector in NOISE_SELECTORS:
            for element in main.select(selector):
                element.decompose()

    @staticmethod
    def _validate_unique_anchors(main: Tag) -> None:
        seen: set[str] = set()
        for element in main.find_all(True):
            values: set[str] = set()
            element_id = element.get("id")
            if isinstance(element_id, str):
                values.add(element_id)
            if element.name == "a":
                element_name = element.get("name")
                if isinstance(element_name, str):
                    values.add(element_name)

            for value in values:
                anchor = value.strip()
                if not anchor:
                    raise DocumentParseError("empty anchor found")
                if anchor in seen:
                    raise DocumentParseError(f"duplicate anchor: {anchor}")
                seen.add(anchor)

    @staticmethod
    def _extract_page_title(main: Tag) -> str:
        headings = main.find_all("h1")
        if not headings:
            raise DocumentParseError("h1 page title not found")
        if len(headings) > 1:
            raise DocumentParseError("multiple h1 page titles found")

        first_heading = main.find(HEADING_NAMES)
        if first_heading is not headings[0]:
            raise DocumentParseError("h1 page title must be the first heading")

        title = _normalize_prose(headings[0].get_text())
        if not title:
            raise DocumentParseError("h1 page title is empty")
        return title

    def _extract_blocks(
        self,
        main: Tag,
    ) -> tuple[list[ParsedContentBlock], list[str]]:
        blocks: list[ParsedContentBlock] = []
        warnings: list[str] = []
        section_stack: list[tuple[int, str, str]] = []
        consumed_containers: set[int] = set()
        paragraph_order = 0

        for element in main.descendants:
            if not isinstance(element, Tag):
                continue
            if _is_inside_consumed_container(element, main, consumed_containers):
                continue

            if element.name in HEADING_NAMES:
                level = int(element.name[1])
                title = _normalize_prose(element.get_text())
                anchor = _heading_anchor(element, main)
                if not title:
                    raise DocumentParseError("heading text is empty")
                if anchor is None:
                    raise DocumentParseError(f"heading has no anchor: {title}")
                if section_stack and level > section_stack[-1][0] + 1:
                    warnings.append(
                        f"heading level jumps from h{section_stack[-1][0]} to h{level}: "
                        f"{title}"
                    )
                section_stack = [
                    section for section in section_stack if section[0] < level
                ]
                section_stack.append((level, title, anchor))
                continue

            block_type: ContentBlockType | None = None
            raw_text: str | None = None
            clean_text: str | None = None
            block_anchor: str | None = None
            list_level: int | None = None
            current_paragraph_order: int | None = None

            if _is_admonition(element):
                raw_text, clean_text = _aggregate_paragraphs(element)
                block_type = ContentBlockType.ADMONITION
                consumed_containers.add(id(element))
            elif element.name == "li":
                raw_text = _list_item_direct_text(element)
                clean_text = _normalize_prose(raw_text)
                block_type = ContentBlockType.LIST_ITEM
                list_level = 1 + sum(
                    1 for parent in element.parents if parent.name == "li"
                )
            elif element.name == "pre":
                raw_text = element.get_text()
                clean_text = raw_text
                block_type = ContentBlockType.CODE
                consumed_containers.add(id(element))
            elif element.name == "dt":
                raw_text = element.get_text()
                clean_text = _normalize_prose(raw_text)
                block_type = ContentBlockType.DEFINITION_TERM
                block_anchor = _own_anchor(element)
            elif element.name == "tr":
                cells = element.find_all(("th", "td"), recursive=False)
                if cells:
                    cell_texts = [_normalize_prose(cell.get_text()) for cell in cells]
                    raw_text = " | ".join(cell_texts)
                    clean_text = raw_text
                    block_type = ContentBlockType.TABLE_ROW
                    consumed_containers.add(id(element))
            elif element.name == "blockquote":
                raw_text, clean_text = _aggregate_paragraphs(element)
                block_type = ContentBlockType.BLOCKQUOTE
                consumed_containers.add(id(element))
            elif element.name == "p":
                if _is_nested_non_paragraph_content(element, main):
                    continue
                raw_text = element.get_text()
                clean_text = _normalize_prose(raw_text)
                block_type = ContentBlockType.PARAGRAPH
                paragraph_order += 1
                current_paragraph_order = paragraph_order
            elif element.name == "img":
                alt = element.get("alt")
                if isinstance(alt, str) and alt.strip():
                    raw_text = alt
                    clean_text = _normalize_prose(alt)
                    block_type = ContentBlockType.IMAGE_ALT

            if block_type is None:
                continue
            if raw_text is None or clean_text is None:
                continue
            if not raw_text.strip() or not clean_text.strip():
                continue
            if not section_stack:
                raise DocumentParseError("body block appears before an anchored heading")

            blocks.append(
                ParsedContentBlock(
                    block_order=len(blocks) + 1,
                    paragraph_order=current_paragraph_order,
                    block_type=block_type,
                    raw_text=raw_text,
                    clean_text=clean_text,
                    section_path=tuple(section[1] for section in section_stack),
                    section_anchor=section_stack[-1][2],
                    block_anchor=block_anchor,
                    list_level=list_level,
                )
            )

        return blocks, warnings


def _normalize_prose(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _own_anchor(element: Tag) -> str | None:
    element_id = element.get("id")
    if isinstance(element_id, str) and element_id.strip():
        return element_id.strip()
    if element.name == "a":
        element_name = element.get("name")
        if isinstance(element_name, str) and element_name.strip():
            return element_name.strip()
    return None


def _heading_anchor(heading: Tag, main: Tag) -> str | None:
    own_anchor = _own_anchor(heading)
    if own_anchor is not None:
        return own_anchor

    for child in heading.find_all(True):
        child_anchor = _own_anchor(child)
        if child_anchor is not None:
            return child_anchor

    for parent in heading.parents:
        if parent is main:
            break
        if isinstance(parent, Tag) and parent.name in {"section", "div"}:
            parent_anchor = _own_anchor(parent)
            if parent_anchor is not None:
                return parent_anchor
    return None


def _is_admonition(element: Tag) -> bool:
    classes = element.get("class", ())
    return isinstance(classes, Iterable) and "admonition" in classes


def _aggregate_paragraphs(element: Tag) -> tuple[str, str]:
    paragraph_texts = [paragraph.get_text().strip() for paragraph in element.find_all("p")]
    paragraph_texts = [text for text in paragraph_texts if text]
    raw_text = "\n".join(paragraph_texts)
    clean_text = "\n".join(_normalize_prose(text) for text in paragraph_texts)
    return raw_text, clean_text


def _list_item_direct_text(element: Tag) -> str:
    parts: list[str] = []
    for child in element.contents:
        if isinstance(child, Tag) and child.name in {"ul", "ol"}:
            continue
        if isinstance(child, Tag):
            parts.append(child.get_text())
        else:
            parts.append(str(child))
    return "".join(parts).strip()


def _is_inside_consumed_container(
    element: Tag,
    main: Tag,
    consumed_containers: set[int],
) -> bool:
    for parent in element.parents:
        if parent is main:
            return False
        if id(parent) in consumed_containers:
            return True
    return False


def _is_nested_non_paragraph_content(element: Tag, main: Tag) -> bool:
    for parent in element.parents:
        if parent is main:
            return False
        if not isinstance(parent, Tag):
            continue
        if parent.name in {"li", "pre", "blockquote", "table"}:
            return True
        if _is_admonition(parent):
            return True
    return False
