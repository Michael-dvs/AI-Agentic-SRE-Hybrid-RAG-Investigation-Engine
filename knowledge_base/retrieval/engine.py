"""Hybrid retrieval engine implementing lexical (BM25), dense (LSA/vector), RRF fusion, and reranker modes (FR-RAG-003, FR-RAG-007, ADR-S04)."""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from typing import Any

import numpy as np

from knowledge_base.retrieval.embeddings import (
    DEFAULT_MULTILINGUAL_MODEL,
    EMBEDDING_DIMENSION,
    MultilingualDenseEmbedder,
)
from knowledge_base.retrieval.models import (
    Citation,
    RetrievalMode,
    RetrievalRequest,
    ScoreType,
    SourceBranch,
)
from knowledge_base.retrieval.prefilter import StrictPreFilter


def tokenize(text: str) -> list[str]:
    """Tokenize technical prose preserving numbers, hyphenated codes, and snake_case identifiers."""
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_-]+", text) if len(t) > 1]


class RetrievalEngine:
    """In-memory multi-mode retrieval engine over published synthetic knowledge chunks.

    Supports lexical_only, dense_only, hybrid_rrf, and hybrid_rerank modes.
    Enforces strict pre-filtering on all branches before candidate retrieval or fusion.
    """

    def __init__(
        self,
        chunks: list[dict[str, Any]],
        index_version: str = "kb-idx-20261111-v1",
        embedding_model_name: str = DEFAULT_MULTILINGUAL_MODEL,
    ) -> None:
        self.chunks = chunks
        self.index_version = index_version
        self.is_healthy: bool = True
        self.embedding_model_name = embedding_model_name

        # Pre-build Lexical BM25 structures
        self.corpus_tokens = [
            tokenize(c["title"] + " " + c["section_path"] + " " + c["content"]) for c in chunks
        ]
        self.doc_lens = [len(tokens) for tokens in self.corpus_tokens]
        self.avgdl = sum(self.doc_lens) / len(self.doc_lens) if self.doc_lens else 1.0
        self.N = len(chunks)

        self.df = Counter()
        for tokens in self.corpus_tokens:
            for t in set(tokens):
                self.df[t] += 1

        self.idf = {
            term: math.log(1.0 + (self.N - freq + 0.5) / (freq + 0.5))
            for term, freq in self.df.items()
        }

        # Pre-build Dense vector index via MultilingualDenseEmbedder (384-d, L2 normalized)
        doc_texts = [c["title"] + " " + c["section_path"] + " " + c["content"] for c in chunks]
        self.embedder = MultilingualDenseEmbedder(model_name=self.embedding_model_name)
        self.dense_vectors = self.embedder.fit_corpus(doc_texts)

    def set_healthy(self, healthy: bool) -> None:
        """Toggle backend health/availability for outage simulation (NFR-016, SC-09, AT-012)."""
        self.is_healthy = healthy

    def _score_bm25(self, query_tokens: list[str], doc_idx: int, k1: float = 1.5, b: float = 0.75) -> float:
        """Compute standard BM25Okapi relevance score for document doc_idx."""
        score = 0.0
        doc_t = self.corpus_tokens[doc_idx]
        tf_counts = Counter(doc_t)
        doc_l = self.doc_lens[doc_idx]
        len_norm = 1.0 - b + b * (doc_l / self.avgdl)
        for q in query_tokens:
            if q in tf_counts:
                term_freq = tf_counts[q]
                denom = term_freq + k1 * len_norm
                score += self.idf.get(q, 0.0) * (term_freq * (k1 + 1.0)) / denom
        return score

    def _score_dense(self, query_text: str, doc_idx: int) -> float:
        """Compute cosine similarity between query dense vector and chunk dense vector."""
        q_vec = self.embedder.embed_query(query_text)
        return float(np.dot(self.dense_vectors[doc_idx], q_vec))

    def query(
        self, request: RetrievalRequest
    ) -> tuple[list[Citation], str, str | None, float]:
        """Execute authorized retrieval request according to requested mode.

        Returns (citations, status, gap_reason, latency_ms).
        """
        start_time = time.perf_counter()

        # Check backend availability
        if not self.is_healthy:
            latency = (time.perf_counter() - start_time) * 1000.0
            return [], "unavailable", "RETRIEVAL_UNAVAILABLE", latency

        # Step 1: Mandatory Pre-Filtering across all modes (FR-RAG-004, RULE-005)
        applicable_pairs = StrictPreFilter.filter_chunks(self.chunks, request)
        if not applicable_pairs:
            latency = (time.perf_counter() - start_time) * 1000.0
            return [], "no_match", "NO_APPLICABLE_RUNBOOK", latency

        q_tokens = tokenize(request.query_text)
        mode = request.retrieval_mode

        # Step 2: Branch scoring
        # Lexical scoring
        bm25_scores = [
            (idx, self._score_bm25(q_tokens, idx)) for idx, _ in applicable_pairs
        ]
        bm25_scores.sort(key=lambda x: x[1], reverse=True)

        # Dense scoring via multilingual embedding vector (384-d, L2 normalized)
        q_vec = self.embedder.embed_query(request.query_text)
        dense_scores = [
            (idx, float(np.dot(self.dense_vectors[idx], q_vec)))
            for idx, _ in applicable_pairs
        ]
        dense_scores.sort(key=lambda x: x[1], reverse=True)

        # Step 3: Selection / Fusion
        ranked_candidates: list[tuple[int, float, ScoreType, SourceBranch]] = []

        if mode == "lexical_only":
            # Filter out zero BM25 scores if possible, unless all are zero
            for idx, sc in bm25_scores:
                if sc > 0.0 or len(ranked_candidates) == 0:
                    ranked_candidates.append((idx, sc, "bm25_sparse", "sparse"))

        elif mode == "dense_only":
            for idx, sc in dense_scores:
                ranked_candidates.append((idx, sc, "cosine_dense", "dense"))

        elif mode == "hybrid_rrf":
            # Reciprocal Rank Fusion (k=60) over Top-30 lexical and Top-30 dense
            k_rrf = 60.0
            rrf_map: dict[int, float] = {}

            for rank, (idx, _) in enumerate(bm25_scores[:30], start=1):
                rrf_map[idx] = rrf_map.get(idx, 0.0) + (1.0 / (k_rrf + rank))

            for rank, (idx, _) in enumerate(dense_scores[:30], start=1):
                rrf_map[idx] = rrf_map.get(idx, 0.0) + (1.0 / (k_rrf + rank))

            sorted_rrf = sorted(rrf_map.items(), key=lambda x: x[1], reverse=True)
            for idx, sc in sorted_rrf:
                ranked_candidates.append((idx, sc, "rrf_fusion", "hybrid"))

        elif mode == "hybrid_rerank":
            # RRF first, then title & section exact term overlap reranking
            k_rrf = 60.0
            rrf_map = {}
            for rank, (idx, _) in enumerate(bm25_scores[:30], start=1):
                rrf_map[idx] = rrf_map.get(idx, 0.0) + (1.0 / (k_rrf + rank))
            for rank, (idx, _) in enumerate(dense_scores[:30], start=1):
                rrf_map[idx] = rrf_map.get(idx, 0.0) + (1.0 / (k_rrf + rank))

            top_candidates = sorted(rrf_map.items(), key=lambda x: x[1], reverse=True)[:15]

            # Rerank with title & section exact term overlap
            reranked = []
            q_token_set = set(q_tokens)
            for idx, rrf_score in top_candidates:
                c = self.chunks[idx]
                sec_tokens = set(tokenize(c["section_path"]))
                title_tokens = set(tokenize(c["title"]))
                overlap = (
                    len(q_token_set.intersection(sec_tokens)) * 0.005
                    + len(q_token_set.intersection(title_tokens)) * 0.003
                )
                final_score = rrf_score + overlap
                reranked.append((idx, final_score))

            reranked.sort(key=lambda x: x[1], reverse=True)
            for idx, sc in reranked:
                ranked_candidates.append((idx, sc, "cross_encoder_rerank", "reranked"))

        # Step 4: Verification and No-Match check (FR-RAG-009, RULE-006)
        if not ranked_candidates:
            latency = (time.perf_counter() - start_time) * 1000.0
            return [], "no_match", "NO_APPLICABLE_RUNBOOK", latency

        top_cand_idx, top_cand_score, _, _ = ranked_candidates[0]

        # Honesty threshold: check if top candidate has meaningful relevance
        # Rather than returning hallucinations on completely unrelated queries
        top_bm25 = dict(bm25_scores).get(top_cand_idx, 0.0)
        top_dense = dict(dense_scores).get(top_cand_idx, 0.0)

        if mode == "lexical_only":
            if top_cand_score < 2.5:
                latency = (time.perf_counter() - start_time) * 1000.0
                return [], "no_match", "NO_APPLICABLE_RUNBOOK", latency
        elif mode == "dense_only":
            if top_cand_score < 0.08:
                latency = (time.perf_counter() - start_time) * 1000.0
                return [], "no_match", "NO_APPLICABLE_RUNBOOK", latency
        else:  # hybrid_rrf / hybrid_rerank
            if top_bm25 < 2.5 and top_dense < 0.08:
                latency = (time.perf_counter() - start_time) * 1000.0
                return [], "no_match", "NO_APPLICABLE_RUNBOOK", latency

        # Step 5: Format citations
        citations: list[Citation] = []
        for idx, score, score_type, source_branch in ranked_candidates[: request.top_k]:
            c = self.chunks[idx]
            # Excerpt: clean first 1000 chars of content
            clean_content = c["content"].strip()
            excerpt = clean_content[:1500] if len(clean_content) > 1500 else clean_content

            citation = Citation(
                chunk_id=c["chunk_id"],
                document_id=c["document_id"],
                document_version=c["document_version"],
                title=c["title"],
                section_path=c["section_path"],
                source_uri=c["source_uri"],
                service_id=c["service_id"],
                environment=c["environment"],
                status=c["status"],
                effective_from=c["effective_from"],
                effective_to=c.get("effective_to"),
                content_hash=c["content_hash"],
                score=score,
                score_type=score_type,
                source_branch=source_branch,
                sanitized_excerpt=excerpt,
                applicability_verified=True,
            )
            citations.append(citation)

        latency = (time.perf_counter() - start_time) * 1000.0
        return citations, "ok", None, latency
