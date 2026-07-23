from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import tiktoken

from curx.services.content_loaders import PAGE_MARKER_PATTERN

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    content: str
    token_count: int
    content_hash: str
    heading_path: list[str]
    page_number: int | None
    location: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class _Section:
    heading_path: list[str]
    page_number: int | None
    heading_level: int | None
    heading: str | None
    lines: list[str] = field(default_factory=list)


class HierarchicalChunker:
    def __init__(
        self,
        *,
        max_tokens: int,
        overlap_tokens: int,
        encoding_name: str = "cl100k_base",
    ) -> None:
        if max_tokens < 64:
            raise ValueError("max_tokens must be at least 64.")
        if overlap_tokens < 0 or overlap_tokens >= max_tokens // 2:
            raise ValueError("overlap_tokens must be non-negative and less than half max_tokens.")
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.encoding = tiktoken.get_encoding(encoding_name)

    def _tokens(self, value: str) -> list[int]:
        return self.encoding.encode(value, disallowed_special=())

    def _decode(self, tokens: list[int]) -> str:
        return self.encoding.decode(tokens).strip()

    def _sections(self, markdown: str) -> list[_Section]:
        headings: list[str] = []
        page_number: int | None = None
        sections: list[_Section] = []
        current = _Section([], None, None, None)

        def flush() -> None:
            nonlocal current
            if current.heading or any(line.strip() for line in current.lines):
                sections.append(current)
            current = _Section(list(headings), page_number, None, None)

        for line in markdown.splitlines():
            page_match = PAGE_MARKER_PATTERN.fullmatch(line.strip())
            if page_match:
                flush()
                page_number = int(page_match.group(1))
                current.page_number = page_number
                continue

            heading_match = HEADING_PATTERN.match(line)
            if heading_match:
                flush()
                level = len(heading_match.group(1))
                heading = heading_match.group(2).strip()
                headings = headings[: level - 1]
                headings.append(heading)
                current = _Section(list(headings), page_number, level, heading)
                continue

            current.lines.append(line)

        flush()
        return sections

    @staticmethod
    def _section_prefix(section: _Section) -> str:
        if section.heading and section.heading_level:
            return f"{'#' * section.heading_level} {section.heading}"
        if section.heading_path:
            return f"## {section.heading_path[-1]}"
        return ""

    @staticmethod
    def _paragraphs(lines: list[str]) -> list[str]:
        paragraphs: list[str] = []
        current: list[str] = []
        in_fence = False
        for line in lines:
            if line.strip().startswith("```"):
                in_fence = not in_fence
            if not line.strip() and not in_fence:
                if current:
                    paragraphs.append("\n".join(current).strip())
                    current = []
                continue
            current.append(line)
        if current:
            paragraphs.append("\n".join(current).strip())
        return [paragraph for paragraph in paragraphs if paragraph]

    def _split_section(self, section: _Section) -> list[str]:
        prefix = self._section_prefix(section)
        body = "\n\n".join(self._paragraphs(section.lines))
        complete = "\n\n".join(part for part in (prefix, body) if part).strip()
        if len(self._tokens(complete)) <= self.max_tokens:
            return [complete] if complete else []

        prefix_tokens = self._tokens(prefix)
        body_budget = self.max_tokens - len(prefix_tokens) - 2
        if body_budget < 32:
            prefix_tokens = prefix_tokens[: self.max_tokens // 4]
            prefix = self._decode(prefix_tokens)
            body_budget = self.max_tokens - len(prefix_tokens) - 2

        units: list[list[int]] = []
        for paragraph in self._paragraphs(section.lines):
            tokens = self._tokens(paragraph)
            if len(tokens) <= body_budget:
                units.append(tokens)
                continue
            step = max(1, body_budget - self.overlap_tokens)
            units.extend(
                tokens[start : start + body_budget]
                for start in range(0, len(tokens), step)
            )

        chunks: list[str] = []
        current_tokens: list[int] = []
        for unit in units:
            separator_cost = 2 if current_tokens else 0
            if current_tokens and len(current_tokens) + separator_cost + len(unit) > body_budget:
                rendered_body = self._decode(current_tokens)
                chunks.append("\n\n".join(part for part in (prefix, rendered_body) if part))
                carry_tokens = (
                    current_tokens[-self.overlap_tokens :] if self.overlap_tokens else []
                )
                current_tokens = (
                    carry_tokens
                    if len(carry_tokens) + 2 + len(unit) <= body_budget
                    else []
                )
            if current_tokens:
                current_tokens.extend(self._tokens("\n\n"))
            current_tokens.extend(unit)
            if len(current_tokens) > body_budget:
                current_tokens = current_tokens[:body_budget]

        if current_tokens:
            rendered_body = self._decode(current_tokens)
            chunks.append("\n\n".join(part for part in (prefix, rendered_body) if part))
        return chunks

    def chunk(self, markdown: str) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        for section in self._sections(markdown):
            for content in self._split_section(section):
                normalized = content.strip()
                if not normalized:
                    continue
                ordinal = len(drafts)
                location_parts = []
                if section.page_number is not None:
                    location_parts.append(f"第 {section.page_number} 页")
                if section.heading_path:
                    location_parts.append(" > ".join(section.heading_path))
                if not location_parts:
                    location_parts.append(f"段落 {ordinal + 1}")
                drafts.append(
                    ChunkDraft(
                        ordinal=ordinal,
                        content=normalized,
                        token_count=len(self._tokens(normalized)),
                        content_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                        heading_path=list(section.heading_path),
                        page_number=section.page_number,
                        location=" · ".join(location_parts),
                    )
                )
        if not drafts:
            raise ValueError("The normalized document produced no chunks.")
        return drafts
