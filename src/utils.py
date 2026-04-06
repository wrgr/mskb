
import hashlib
import json
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
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_json(obj: Any, path: Path) -> None:
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def normalize_title(text: str) -> str:
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
    text = _coerce_text(text)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def stable_hash(*parts: str) -> str:
    joined = "||".join(_coerce_text(part) for part in parts)
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def invert_abstract_index(inv_idx: Dict[str, list]) -> str:
    if not inv_idx:
        return ""
    terms = []
    for token, positions in inv_idx.items():
        for p in positions:
            terms.append((p, token))
    return " ".join(token for p, token in sorted(terms))


def write_df(df: pd.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    if path.suffix == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)
