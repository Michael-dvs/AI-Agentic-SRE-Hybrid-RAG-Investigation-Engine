"""Markdown frontmatter and JSON document parsing module."""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class ParsedDocument:
    file_path: pathlib.Path
    metadata: dict[str, Any]
    body: str
    raw_content: str


_FRONTMATTER_RE = re.compile(
    r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$",
    re.DOTALL,
)


def parse_markdown_document(file_path: pathlib.Path | str) -> ParsedDocument:
    """Parse a Markdown document containing YAML frontmatter or a JSON document."""
    path = pathlib.Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Document file not found: {path}")

    raw_text = path.read_text(encoding="utf-8")

    if path.suffix.lower() == ".json":
        data = json.loads(raw_text)
        if not isinstance(data, dict):
            raise ValueError(f"JSON document must be an object: {path}")
        body = data.pop("body", "") or data.pop("content", "")
        return ParsedDocument(
            file_path=path,
            metadata=data,
            body=body,
            raw_content=raw_text,
        )

    match = _FRONTMATTER_RE.match(raw_text)
    if not match:
        raise ValueError(
            f"Document {path.name} is missing valid YAML frontmatter delimiter (--- ... ---)"
        )

    fm_text, body = match.groups()
    try:
        metadata = yaml.safe_load(fm_text) or {}
    except Exception as exc:
        raise ValueError(f"Invalid YAML frontmatter in {path.name}: {exc}") from exc

    if not isinstance(metadata, dict):
        raise ValueError(f"Frontmatter in {path.name} must be a dictionary")

    return ParsedDocument(
        file_path=path,
        metadata=metadata,
        body=body.strip(),
        raw_content=raw_text,
    )

