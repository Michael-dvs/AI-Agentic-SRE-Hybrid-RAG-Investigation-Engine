"""Index versioning, publish, obsolete transition, tombstone, and rollback lifecycle (FR-RAG-008, SC-10, AT-007)."""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import pathlib
from dataclasses import asdict, dataclass, field
from typing import Any

from knowledge_base.ingestion.chunker import StructureAwareChunker
from knowledge_base.ingestion.parser import parse_markdown_document
from knowledge_base.ingestion.sanitizer import RedactionReport, sanitize_document_text
from knowledge_base.ingestion.validator import validate_document_metadata


@dataclass
class IndexManifest:
    index_version: str
    active_alias: str
    created_at: str
    document_count: int
    chunk_count: int
    manifest_hash: str
    chunks: list[dict[str, Any]]
    documents_summary: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_version": self.index_version,
            "active_alias": self.active_alias,
            "created_at": self.created_at,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "manifest_hash": self.manifest_hash,
            "documents_summary": self.documents_summary,
            "chunks": self.chunks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexManifest:
        return cls(
            index_version=data["index_version"],
            active_alias=data["active_alias"],
            created_at=data["created_at"],
            document_count=data["document_count"],
            chunk_count=data["chunk_count"],
            manifest_hash=data["manifest_hash"],
            chunks=data.get("chunks", []),
            documents_summary=data.get("documents_summary", []),
        )


def compute_manifest_hash(chunks: list[dict[str, Any]]) -> str:
    """Compute deterministic SHA-256 fingerprint from ordered chunk IDs, versions, and content hashes."""
    sorted_signatures = sorted(
        f"{c['chunk_id']}::{c['document_id']}::{c['document_version']}::{c['status']}::{c['content_hash']}"
        for c in chunks
    )
    combined = "\n".join(sorted_signatures).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


class KnowledgeLifecycleManager:
    """Manages the full lifecycle of synthetic knowledge base indexes:

    Publishing, version superseding (obsolete transition for SC-10/RAG-01),
    tombstoning, and atomic alias rollback.
    """

    def __init__(self, active_alias: str = "kb_active_alias") -> None:
        self.active_alias = active_alias
        self.chunker = StructureAwareChunker()

    def build_manifest_from_corpus(
        self,
        corpus_dir: pathlib.Path | str,
        index_version: str,
        redaction_report: RedactionReport | None = None,
    ) -> tuple[IndexManifest, RedactionReport]:
        """Ingest all valid documents in corpus_dir and produce a sealed IndexManifest."""
        corpus_path = pathlib.Path(corpus_dir).resolve()
        if not corpus_path.is_dir():
            raise FileNotFoundError(f"Corpus directory not found: {corpus_path}")

        report = redaction_report or RedactionReport()
        doc_files = sorted(
            [p for p in corpus_path.rglob("*") if p.suffix.lower() in (".md", ".json") and not p.name.startswith(".")]
        )

        all_chunks: list[dict[str, Any]] = []
        doc_summaries: list[dict[str, Any]] = []

        for doc_file in doc_files:
            parsed = parse_markdown_document(doc_file)
            meta = validate_document_metadata(parsed.metadata, file_path=doc_file.name)
            report.documents_scanned += 1

            # Pre-ingestion sanitizer (SEC-03)
            sanitized_res = sanitize_document_text(parsed.body, document_id=meta.document_id, report=report)

            # Structure-aware chunking
            rel_path = doc_file.relative_to(corpus_path).as_posix()
            chunk_res = self.chunker.chunk(
                metadata=meta,
                sanitized_body=sanitized_res.sanitized_text,
                index_version=index_version,
                source_rel_path=rel_path,
            )

            all_chunks.extend(chunk_res.chunks)
            doc_summaries.append(
                {
                    "document_id": meta.document_id,
                    "document_version": meta.document_version,
                    "title": meta.title,
                    "service_id": meta.service_id,
                    "status": meta.status,
                    "classification": meta.classification,
                    "effective_from": meta.effective_from,
                    "effective_to": meta.effective_to,
                    "chunk_count": chunk_res.chunk_count,
                    "source_file": rel_path,
                    "document_sha256": hashlib.sha256(parsed.raw_content.encode("utf-8")).hexdigest(),
                }
            )

        manifest_hash = compute_manifest_hash(all_chunks)
        now_z = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        manifest = IndexManifest(
            index_version=index_version,
            active_alias=self.active_alias,
            created_at=now_z,
            document_count=len(doc_summaries),
            chunk_count=len(all_chunks),
            manifest_hash=manifest_hash,
            chunks=all_chunks,
            documents_summary=doc_summaries,
        )

        return manifest, report

    def supersede_document(
        self,
        current_manifest: IndexManifest,
        new_document_path: pathlib.Path | str,
        new_index_version: str,
        redaction_report: RedactionReport | None = None,
    ) -> tuple[IndexManifest, dict[str, Any]]:
        """Publish a new document version, automatically marking older versions as obsolete (SC-10, RAG-01)."""
        new_doc_p = pathlib.Path(new_document_path).resolve()
        parsed = parse_markdown_document(new_doc_p)
        new_meta = validate_document_metadata(parsed.metadata, file_path=new_doc_p.name)

        report = redaction_report or RedactionReport()
        report.documents_scanned += 1
        sanitized_res = sanitize_document_text(parsed.body, document_id=new_meta.document_id, report=report)

        new_chunk_res = self.chunker.chunk(
            metadata=new_meta,
            sanitized_body=sanitized_res.sanitized_text,
            index_version=new_index_version,
            source_rel_path=new_doc_p.name,
        )

        updated_chunks: list[dict[str, Any]] = []
        superseded_count = 0
        now_z = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        for c in current_manifest.chunks:
            chunk_copy = copy.deepcopy(c)
            # If same document_id but older version: mark as obsolete
            if chunk_copy["document_id"] == new_meta.document_id and chunk_copy["document_version"] != new_meta.document_version:
                chunk_copy["status"] = "obsolete"
                if chunk_copy["effective_to"] is None:
                    chunk_copy["effective_to"] = new_meta.effective_from
                chunk_copy["index_version"] = new_index_version
                chunk_copy["updated_at"] = now_z
                superseded_count += 1
                updated_chunks.append(chunk_copy)
            elif chunk_copy["document_id"] == new_meta.document_id and chunk_copy["document_version"] == new_meta.document_version:
                # Replace matching version if re-ingesting
                continue
            else:
                chunk_copy["index_version"] = new_index_version
                updated_chunks.append(chunk_copy)

        # Append new version chunks
        updated_chunks.extend(new_chunk_res.chunks)

        new_manifest_hash = compute_manifest_hash(updated_chunks)

        # Update documents summary
        updated_summaries = [s for s in current_manifest.documents_summary if not (s["document_id"] == new_meta.document_id and s["document_version"] == new_meta.document_version)]
        for s in updated_summaries:
            if s["document_id"] == new_meta.document_id and s["document_version"] != new_meta.document_version:
                s["status"] = "obsolete"
                s["effective_to"] = new_meta.effective_from

        updated_summaries.append({
            "document_id": new_meta.document_id,
            "document_version": new_meta.document_version,
            "title": new_meta.title,
            "service_id": new_meta.service_id,
            "status": new_meta.status,
            "classification": new_meta.classification,
            "effective_from": new_meta.effective_from,
            "effective_to": new_meta.effective_to,
            "chunk_count": new_chunk_res.chunk_count,
            "source_file": new_doc_p.name,
            "document_sha256": hashlib.sha256(parsed.raw_content.encode("utf-8")).hexdigest(),
        })

        new_manifest = IndexManifest(
            index_version=new_index_version,
            active_alias=self.active_alias,
            created_at=now_z,
            document_count=len(updated_summaries),
            chunk_count=len(updated_chunks),
            manifest_hash=new_manifest_hash,
            chunks=updated_chunks,
            documents_summary=updated_summaries,
        )

        record = {
            "operation": "supersede_document",
            "document_id": new_meta.document_id,
            "new_version": new_meta.document_version,
            "status_transition": "obsolete_transition_applied",
            "chunks_superseded_to_obsolete": superseded_count,
            "new_chunks_added": new_chunk_res.chunk_count,
            "prior_manifest_hash": current_manifest.manifest_hash,
            "new_manifest_hash": new_manifest_hash,
            "timestamp": now_z,
        }

        return new_manifest, record

    def tombstone_document(
        self,
        current_manifest: IndexManifest,
        document_id: str,
        new_index_version: str,
        reason: str = "administrative_withdrawal",
    ) -> tuple[IndexManifest, dict[str, Any]]:
        """Withdraw/tombstone a document so its chunks are marked 'withdrawn' and excluded from retrieval."""
        updated_chunks: list[dict[str, Any]] = []
        withdrawn_count = 0
        now_z = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        for c in current_manifest.chunks:
            chunk_copy = copy.deepcopy(c)
            if chunk_copy["document_id"] == document_id:
                chunk_copy["status"] = "withdrawn"
                chunk_copy["index_version"] = new_index_version
                chunk_copy["updated_at"] = now_z
                withdrawn_count += 1
            else:
                chunk_copy["index_version"] = new_index_version
            updated_chunks.append(chunk_copy)

        new_manifest_hash = compute_manifest_hash(updated_chunks)

        updated_summaries = copy.deepcopy(current_manifest.documents_summary)
        for s in updated_summaries:
            if s["document_id"] == document_id:
                s["status"] = "withdrawn"

        new_manifest = IndexManifest(
            index_version=new_index_version,
            active_alias=self.active_alias,
            created_at=now_z,
            document_count=len(updated_summaries),
            chunk_count=len(updated_chunks),
            manifest_hash=new_manifest_hash,
            chunks=updated_chunks,
            documents_summary=updated_summaries,
        )

        record = {
            "operation": "tombstone_document",
            "document_id": document_id,
            "reason": reason,
            "chunks_withdrawn": withdrawn_count,
            "prior_manifest_hash": current_manifest.manifest_hash,
            "new_manifest_hash": new_manifest_hash,
            "timestamp": now_z,
        }

        return new_manifest, record

    def rollback_manifest(
        self,
        target_manifest: IndexManifest,
        rollback_reason: str = "operator_rollback_request",
    ) -> tuple[IndexManifest, dict[str, Any]]:
        """Rollback the active alias to a previous manifest, verifying its cryptographic hash."""
        recalculated_hash = compute_manifest_hash(target_manifest.chunks)
        if recalculated_hash != target_manifest.manifest_hash:
            raise ValueError(
                f"Rollback integrity verification failed: expected {target_manifest.manifest_hash}, got {recalculated_hash}"
            )

        now_z = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        record = {
            "operation": "rollback_index",
            "restored_index_version": target_manifest.index_version,
            "active_alias": self.active_alias,
            "reason": rollback_reason,
            "manifest_hash_verified": True,
            "verified_hash": recalculated_hash,
            "chunk_count": target_manifest.chunk_count,
            "timestamp": now_z,
        }
        return target_manifest, record

