#!/usr/bin/env python3
"""Build auditable, corpus-derived scores for the homepage research map.

The controlled inputs are concept names, semantic line breaks, and aliases in
``scripts/research_theme_concepts.json``. Paper relevance, prevalence, theme
similarity, and family-color weights are derived deterministically from the
linked full-text PDFs and written to ``_data/research_theme_scores.json``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import unicodedata
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "scripts" / "research_theme_concepts.json"
OUTPUT_PATH = ROOT / "_data" / "research_theme_scores.json"
CACHE_DIR = ROOT / "tmp" / "pdfs" / "research-theme-corpus"

FIELD_WEIGHTS = {"title": 4.0, "abstract": 3.0, "headings": 2.0, "body": 1.0}
FIELD_B = {"title": 0.20, "abstract": 0.60, "headings": 0.50, "body": 0.75}
K1 = 1.20

NUMBERED_HEADING_RE = re.compile(
    r"^(?:[IVXLCDM]+|\d+(?:\.\d+){0,3})[.)]?\s*[A-Z][A-Za-z][^\n]{1,105}$"
)
NAMED_HEADING_RE = re.compile(
    r"^(?:abstract|introduction|background|related work|methods?|results?|"
    r"discussion|conclusion|conclusions|appendix|proofs?)$",
    re.IGNORECASE,
)
ABSTRACT_START_RE = re.compile(r"(?:^|\n)\s*abstract\s*(?:\n|[:.-])", re.IGNORECASE)
INTRO_RE = re.compile(
    r"(?:^|\n)\s*(?:1\s*[.)]?\s*)?introduction\b", re.IGNORECASE
)
REFERENCE_RE = re.compile(
    r"(?:^|\n)\s*(?:references|bibliography)\s*(?:\n|$)", re.IGNORECASE
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("\u00ad", "")
    text = re.sub(r"([A-Za-z])-\s*\n\s*([A-Za-z])", r"\1 \2", text)
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def word_count(text: str) -> int:
    return len(text.split())


def looks_like_heading(line: str) -> bool:
    if not 3 <= len(line) <= 120 or len(line.split()) > 14:
        return False
    if re.search(r"(?:\.\s*){3,}", line):
        return False
    return bool(NUMBERED_HEADING_RE.match(line) or NAMED_HEADING_RE.match(line))


def download_pdf(url: str, destination: Path) -> bytes:
    if destination.exists():
        data = destination.read_bytes()
        if data.startswith(b"%PDF") and len(data) > 10_000:
            return data
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Moriartycc-research-map-builder/1.0"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    if not data.startswith(b"%PDF") or len(data) <= 10_000:
        raise ValueError(f"Downloaded content is not a valid PDF: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return data


def extract_fields(pdf_path: Path, title: str) -> tuple[dict[str, str], dict[str, int]]:
    reader = PdfReader(str(pdf_path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    raw = "\n".join(pages).replace("\r\n", "\n").replace("\r", "\n")
    if len(normalized_text(raw)) < 5_000:
        raise ValueError(f"Too little extractable text in {pdf_path.name}")

    abstract = ""
    abstract_end = 0
    abstract_match = ABSTRACT_START_RE.search(raw[: max(15_000, len(raw) // 4)])
    if abstract_match:
        intro_match = INTRO_RE.search(raw, abstract_match.end())
        if intro_match and intro_match.start() - abstract_match.end() < 12_000:
            abstract = raw[abstract_match.end() : intro_match.start()]
            abstract_end = intro_match.start()

    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
    headings = [line for line in lines if looks_like_heading(line)]

    body = raw[abstract_end:] if abstract_end else raw
    reference_matches = list(REFERENCE_RE.finditer(body))
    late_matches = [match for match in reference_matches if match.start() > len(body) * 0.10]
    if late_matches:
        body = body[: late_matches[0].start()]

    # Avoid giving headings both heading-field and body-field weight.
    heading_keys = {normalized_text(line) for line in headings}
    body_lines = [
        line for line in body.splitlines() if normalized_text(line) not in heading_keys
    ]

    fields = {
        "title": normalized_text(title),
        "abstract": normalized_text(abstract),
        "headings": normalized_text("\n".join(headings)),
        "body": normalized_text("\n".join(body_lines)),
    }
    stats = {
        "pages": len(reader.pages),
        "extracted_characters": len(raw),
        "abstract_words": word_count(fields["abstract"]),
        "heading_count": len(headings),
        "body_words": word_count(fields["body"]),
    }
    return fields, stats


def alias_patterns(aliases: list[str]) -> dict[str, re.Pattern[str]]:
    normalized = sorted(
        {normalized_text(alias) for alias in aliases if normalized_text(alias)},
        key=lambda alias: (-len(alias.split()), -len(alias), alias),
    )
    return {
        alias: re.compile(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])")
        for alias in normalized
    }


def longest_nonoverlap_counts(
    text: str, patterns: dict[str, re.Pattern[str]]
) -> Counter[str]:
    candidates: list[tuple[int, int, str]] = []
    for alias, pattern in patterns.items():
        candidates.extend((m.start(), m.end(), alias) for m in pattern.finditer(text))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))

    counts: Counter[str] = Counter()
    occupied_until = -1
    for start, end, alias in candidates:
        if start < occupied_until:
            continue
        counts[alias] += 1
        occupied_until = end
    return counts


def cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def rounded(value: float) -> float:
    return round(value, 6)


def build() -> dict[str, Any]:
    config_bytes = CONFIG_PATH.read_bytes()
    config = json.loads(config_bytes)
    papers = config["papers"]
    concepts = config["concepts"]
    families = config["families"]
    paper_ids = [paper["id"] for paper in papers]

    corpus: dict[str, dict[str, str]] = {}
    source_metadata: list[dict[str, Any]] = []
    for paper in papers:
        pdf_path = CACHE_DIR / f"{paper['id']}.pdf"
        data = download_pdf(paper["pdf_url"], pdf_path)
        fields, stats = extract_fields(pdf_path, paper["title"])
        corpus[paper["id"]] = fields
        source_metadata.append(
            {
                "id": paper["id"],
                "title": paper["title"],
                "year": paper["year"],
                "pdf_url": paper["pdf_url"],
                "pdf_sha256": sha256_bytes(data),
                **stats,
            }
        )
        print(
            f"{paper['id']}: {stats['pages']} pages, "
            f"{stats['body_words']:,} body words",
            file=sys.stderr,
        )

    average_lengths = {
        field: sum(word_count(corpus[paper_id][field]) for paper_id in paper_ids)
        / len(paper_ids)
        for field in FIELD_WEIGHTS
    }

    concept_rows: list[dict[str, Any]] = []
    concept_vectors: dict[str, list[float]] = {}
    for concept in concepts:
        patterns = alias_patterns(concept["aliases"])
        counts: dict[str, dict[str, Counter[str]]] = {}
        for paper_id in paper_ids:
            counts[paper_id] = {
                field: longest_nonoverlap_counts(corpus[paper_id][field], patterns)
                for field in FIELD_WEIGHTS
            }

        document_frequency = {
            alias: sum(
                any(counts[paper_id][field][alias] for field in FIELD_WEIGHTS)
                for paper_id in paper_ids
            )
            for alias in patterns
        }
        raw_scores: dict[str, float] = {}
        for paper_id in paper_ids:
            score = 0.0
            for alias in patterns:
                df = document_frequency[alias]
                if df == 0:
                    continue
                combined_tf = 0.0
                for field, weight in FIELD_WEIGHTS.items():
                    length = word_count(corpus[paper_id][field])
                    average = max(average_lengths[field], 1.0)
                    denominator = 1.0 - FIELD_B[field] + FIELD_B[field] * length / average
                    combined_tf += weight * counts[paper_id][field][alias] / denominator
                if combined_tf:
                    idf = math.log(1.0 + (len(paper_ids) - df + 0.5) / (df + 0.5))
                    score += idf * ((K1 + 1.0) * combined_tf) / (K1 + combined_tf)
            raw_scores[paper_id] = score

        maximum = max(raw_scores.values(), default=0.0)
        if maximum <= 0:
            raise ValueError(f"Concept has no corpus evidence: {concept['label']}")
        vector = [raw_scores[paper_id] / maximum for paper_id in paper_ids]
        concept_vectors[concept["label"]] = vector
        concept_rows.append(
            {
                "label": concept["label"],
                "kind": concept["kind"],
                **({"family": concept["family"]} if "family" in concept else {}),
                "lines": concept["lines"],
                "aliases": sorted(patterns),
                "paper_scores": {
                    paper_id: rounded(value) for paper_id, value in zip(paper_ids, vector)
                },
                "prevalence": rounded(sum(vector) / len(vector)),
                "alias_document_frequency": document_frequency,
                "alias_papers": {
                    alias: [
                        paper_id
                        for paper_id in paper_ids
                        if any(counts[paper_id][field][alias] for field in FIELD_WEIGHTS)
                    ]
                    for alias in patterns
                },
            }
        )

    themes = [row for row in concept_rows if row["kind"] == "theme"]
    family_vectors: dict[str, list[float]] = {}
    for family in families:
        members = [row["label"] for row in themes if row["family"] == family]
        family_vectors[family] = [
            max(concept_vectors[label][index] for label in members)
            for index in range(len(paper_ids))
        ]

    for row in concept_rows:
        vector = concept_vectors[row["label"]]
        similarities = {family: cosine(vector, family_vectors[family]) for family in families}
        total = sum(similarities.values())
        row["family_weights"] = {
            family: rounded(similarities[family] / total if total else 1.0 / len(families))
            for family in families
        }
        row["theme_similarities"] = {
            theme["label"]: rounded(cosine(vector, concept_vectors[theme["label"]]))
            for theme in themes
        }

    return {
        "metadata": {
            "method": "BM25F phrase scoring over full-text PDFs",
            "normalization": "Each concept's paper scores are divided by that concept's maximum paper score; prevalence is their mean.",
            "similarity": "Cosine similarity between 14-paper relevance vectors.",
            "family_profile": "Per paper, the maximum normalized relevance among themes assigned to the family.",
            "family_color_weights": "Cosine similarities to the six family profiles, normalized to sum to one.",
            "alias_matching": "Case-folded exact phrases with punctuation normalized to spaces; longest overlapping alias wins.",
            "references_excluded": True,
            "k1": K1,
            "field_weights": FIELD_WEIGHTS,
            "field_length_normalization": FIELD_B,
            "concept_config_sha256": sha256_bytes(config_bytes),
            "paper_order": paper_ids,
            "families": families,
        },
        "sources": source_metadata,
        "concepts": concept_rows,
    }


def main() -> None:
    result = build()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
