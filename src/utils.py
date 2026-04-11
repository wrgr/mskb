"""Shared utility functions used across all pipeline stages."""

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import yaml


def _coerce_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def load_config(path: str) -> Dict[str, Any]:
    """Load a YAML config file and return its contents as a dict."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    mailto_override = str(os.environ.get("OPENALEX_MAILTO", "")).strip()
    if mailto_override:
        cfg["email"] = mailto_override
    return cfg


def ensure_dir(path: Path) -> None:
    """Create directory (and all parents) if it does not already exist."""
    path.mkdir(parents=True, exist_ok=True)


def save_json(obj: Any, path: Path) -> None:
    """Serialize obj to indented JSON and write to path, creating parents as needed."""
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def normalize_title(text: str) -> str:
    """Normalize a title string for fuzzy deduplication by stripping noise and lowercasing."""
    text = _coerce_text(text)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"\(.*?preprint.*?\)", " ", text)
    text = re.sub(r"\b(erratum|correction|supplementary|preprint|biorxiv|arxiv|extended version)\b", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_name(text: str) -> str:
    """Normalize an author name string for fuzzy comparison."""
    text = _coerce_text(text)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def stable_hash(*parts: str) -> str:
    """Return a stable MD5 hex digest of all parts joined with a separator."""
    joined = "||".join(_coerce_text(part) for part in parts)
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, reading in 1 MB chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def invert_abstract_index(inv_idx: Dict[str, list]) -> str:
    """Reconstruct abstract text from an OpenAlex inverted index mapping tokens to positions."""
    if not inv_idx:
        return ""
    terms = []
    for token, positions in inv_idx.items():
        for p in positions:
            terms.append((p, token))
    return " ".join(token for p, token in sorted(terms))


def write_df(df: pd.DataFrame, path: Path) -> None:
    """Write a DataFrame to Parquet or CSV depending on the path suffix."""
    ensure_dir(path.parent)
    if path.suffix == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)


def load_downstream_corpus(graph_dir: Path) -> tuple[pd.DataFrame, Path]:
    """Load corpus for downstream stages, preferring curated tracked outputs.

    Priority:
      1) core_corpus_tracked_with_t4.csv
      2) core_corpus_selected.csv
      3) scored_papers.csv filtered by in_final_corpus / tier
    """
    tracked_path = graph_dir / "core_corpus_tracked_with_t4.csv"
    selected_path = graph_dir / "core_corpus_selected.csv"
    scored_path = graph_dir / "scored_papers.csv"

    source_path: Path
    if tracked_path.exists():
        source_path = tracked_path
    elif selected_path.exists():
        source_path = selected_path
    elif scored_path.exists():
        source_path = scored_path
    else:
        raise FileNotFoundError(
            f"Missing downstream corpus input. Checked: {tracked_path}, {selected_path}, {scored_path}"
        )

    papers = pd.read_csv(source_path, low_memory=False)
    if source_path.name == "scored_papers.csv":
        has_in_final = "in_final_corpus" in papers.columns
        if has_in_final:
            papers["in_final_corpus"] = papers["in_final_corpus"].fillna(0).astype(int)
            papers = papers[papers["in_final_corpus"] == 1].copy()
        elif "tier" in papers.columns:
            papers = papers[papers["tier"].astype(str).isin(["included", "seed_neighbor"])].copy()
    elif "tier" in papers.columns:
        papers = papers[papers["tier"].astype(str).isin(["included", "seed_neighbor"])].copy()
    return papers, source_path
