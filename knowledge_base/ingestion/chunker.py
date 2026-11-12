"""Structure-aware chunker with provenance hashing (FR-RAG-002, ADR-S04)."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from knowledge_base.ingestion.validator import DocumentMetadata


@dataclass(frozen=True)
class ChunkerResult:
    document_id: str
    document_version: str
    chunk_count: int
    chunks: list[dict[str, Any]]


_CONTRACT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
    / "knowledge-chunk.v1.schema.json"
)

# Load and prepare validator once
_SCHEMA: dict[str, Any] = {}
_VALIDATOR: Draft202012Validator | None = None

if _CONTRACT_PATH.exists():
    _SCHEMA = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    _VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


class StructureAwareChunker:
    """Structure-aware Markdown chunker respecting heading hierarchies (#, ##, ###).

    Target chunk length: 350-700 tokens (~1400-2800 characters) with 50-100 token overlap.
    """

    def __init__(
        self,
        min_chars: int = 150,
        target_chars: int = 2000,
        max_chars: int = 3500,
        overlap_chars: int = 300,
    ) -> None:
        self.min_chars = min_chars
        self.target_chars = target_chars
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk(
        self,
        metadata: DocumentMetadata,
        sanitized_body: str,
        index_version: str,
        source_rel_path: str = "",
    ) -> ChunkerResult:
        """Parse structured sections and produce compliant knowledge chunks."""
        sections = self._parse_heading_sections(metadata.title, sanitized_body)
        raw_chunks: list[tuple[str, str]] = []  # (section_path, content)

        for heading_path, section_text in sections:
            clean_text = section_text.strip()
            if not clean_text:
                continue

            # If section fits comfortably, keep as a single chunk
            if len(clean_text) <= self.max_chars:
                raw_chunks.append((heading_path, clean_text))
            else:
                # Split large section by paragraphs with overlap
                sub_chunks = self._split_by_paragraphs(clean_text)
                for sub_idx, sub_text in enumerate(sub_chunks, start=1):
                    sub_path = f"{heading_path} (Bagian {sub_idx})" if len(sub_chunks) > 1 else heading_path
                    raw_chunks.append((sub_path, sub_text))

        # Build schema-compliant chunks
        chunks: list[dict[str, Any]] = []
        doc_slug = metadata.document_id.replace("/", "_")
        ver_slug = metadata.document_version.replace("/", "_")
        source_uri = f"kb://corpus/{metadata.service_id}/{source_rel_path or (doc_slug + '.md')}"

        for seq_idx, (section_path, content) in enumerate(raw_chunks, start=1):
            chunk_id = f"chk-{doc_slug}-v{ver_slug}-{seq_idx:03d}"
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            chunk_dict: dict[str, Any] = {
                "schema_version": "1.0",
                "chunk_id": chunk_id,
                "document_id": metadata.document_id,
                "document_version": metadata.document_version,
                "index_version": index_version,
                "title": metadata.title,
                "source_uri": source_uri,
                "section_path": section_path,
                "service_id": metadata.service_id,
                "service.name": metadata.service_name,
                "environment": metadata.environment,
                "application": metadata.application,
                "component": metadata.component,
                "status": metadata.status,
                "effective_from": metadata.effective_from,
                "effective_to": metadata.effective_to,
                "content_hash": content_hash,
                "classification": metadata.classification,
                "allowed_groups": list(metadata.allowed_groups),
                "owner_ref": metadata.owner_ref,
                "language": metadata.language,
                "content": content,
                "updated_at": metadata.updated_at,
            }

            # Validate against Draft 2020-12 contract
            if _VALIDATOR is not None:
                errors = list(_VALIDATOR.iter_errors(chunk_dict))
                if errors:
                    err_msg = "; ".join(e.message for e in errors)
                    raise ValueError(f"Generated chunk {chunk_id} violates knowledge-chunk.v1 schema: {err_msg}")

            chunks.append(chunk_dict)

        return ChunkerResult(
            document_id=metadata.document_id,
            document_version=metadata.document_version,
            chunk_count=len(chunks),
            chunks=chunks,
        )

    def _parse_heading_sections(self, doc_title: str, text: str) -> list[tuple[str, str]]:
        """Extract sections grouped by heading hierarchy (#, ##, ###)."""
        lines = text.splitlines(keepends=True)
        sections: list[tuple[str, str]] = []

        h1: str = doc_title
        h2: str = ""
        h3: str = ""

        current_lines: list[str] = []

        def _current_path() -> str:
            parts = [h1]
            if h2:
                parts.append(h2)
            if h3:
                parts.append(h3)
            return " > ".join(parts)

        for line in lines:
            h1_match = re.match(r"^#\s+(.+)$", line)
            h2_match = re.match(r"^##\s+(.+)$", line)
            h3_match = re.match(r"^###\s+(.+)$", line)

            if h1_match:
                if current_lines:
                    sections.append((_current_path(), "".join(current_lines)))
                    current_lines = []
                h1 = h1_match.group(1).strip()
                h2 = ""
                h3 = ""
            elif h2_match:
                if current_lines:
                    sections.append((_current_path(), "".join(current_lines)))
                    current_lines = []
                h2 = h2_match.group(1).strip()
                h3 = ""
            elif h3_match:
                if current_lines:
                    sections.append((_current_path(), "".join(current_lines)))
                    current_lines = []
                h3 = h3_match.group(1).strip()
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((_current_path(), "".join(current_lines)))

        return sections

    def _split_by_paragraphs(self, text: str) -> list[str]:
        """Split text across paragraph breaks while maintaining bounded chunk sizes and overlap."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return [text]

        chunks: list[str] = []
        current_chunk_paras: list[str] = []
        current_len = 0

        for p in paragraphs:
            p_len = len(p)
            if current_len + p_len > self.target_chars and current_chunk_paras:
                chunks.append("\n\n".join(current_chunk_paras))
                # retain last paragraph for overlap if reasonable
                if len(current_chunk_paras[-1]) <= self.overlap_chars:
                    current_chunk_paras = [current_chunk_paras[-1], p]
                    current_len = len(current_chunk_paras[0]) + p_len + 2
                else:
                    current_chunk_paras = [p]
                    current_len = p_len
            else:
                current_chunk_paras.append(p)
                current_len += p_len + 2

        if current_chunk_paras:
            chunks.append("\n\n".join(current_chunk_paras))

        return chunks


def chunk_document(
    metadata: DocumentMetadata,
    sanitized_body: str,
    index_version: str,
    source_rel_path: str = "",
) -> ChunkerResult:
    """Convenience helper to chunk a document using default structure-aware settings."""
    chunker = StructureAwareChunker()
    return chunker.chunk(
        metadata=metadata,
        sanitized_body=sanitized_body,
        index_version=index_version,
        source_rel_path=source_rel_path,
    )

