"""HTTP client for the Semantic Scholar Graph API with caching and retry logic."""

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

import requests


class SemanticScholarClient:
    def __init__(
        self,
        base_url: str = "https://api.semanticscholar.org/graph/v1",
        api_key: str = "",
        timeout: int = 30,
        cache_dir: Optional[Path] = None,
        max_retries: int = 3,
        max_retry_sleep_s: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.timeout = max(1, int(timeout))
        self.max_retries = max(1, int(max_retries))
        self.max_retry_sleep_s = max(1.0, float(max_retry_sleep_s))
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "mskb/0.1"})
        if self.api_key:
            self.session.headers.update({"x-api-key": self.api_key})

    def _cache_path(self, path: str, params: Dict) -> Optional[Path]:
        if not self.cache_dir:
            return None
        key = json.dumps({"path": path, "params": params}, sort_keys=True, separators=(",", ":"))
        return self.cache_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"

    @staticmethod
    def _tmp_cache_path(cache_path: Path) -> Path:
        token = f".{os.getpid()}.{threading.get_ident()}.{time.time_ns()}"
        return cache_path.with_name(f"{cache_path.name}{token}.tmp")

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        params = params or {}
        cache_path = self._cache_path(path, params)
        if cache_path and cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                cache_path.unlink(missing_ok=True)

        url = f"{self.base_url}{path}"
        payload: Dict = {}
        for attempt in range(self.max_retries):
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code in {400, 404}:
                payload = {"_not_found": True}
                break
            if r.status_code in {401, 403}:
                payload = {"_auth_error": True}
                break
            if r.status_code == 429 or r.status_code >= 500:
                if attempt + 1 >= self.max_retries:
                    r.raise_for_status()
                retry_after = (r.headers.get("retry-after") or "").strip()
                sleep_s = 1.5 * (attempt + 1)
                if retry_after.isdigit():
                    sleep_s = float(retry_after)
                time.sleep(min(sleep_s, self.max_retry_sleep_s))
                continue
            r.raise_for_status()
            payload = r.json()
            break

        if cache_path:
            tmp_path = self._tmp_cache_path(cache_path)
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f)
                tmp_path.replace(cache_path)
            except OSError:
                tmp_path.unlink(missing_ok=True)
        return payload

    def get_references_by_doi(self, doi: str, max_refs: int = 250) -> List[Dict]:
        doi = str(doi or "").strip()
        if not doi:
            return []
        out: List[Dict] = []
        offset = 0
        limit = min(100, max(1, int(max_refs)))
        encoded_id = quote(f"DOI:{doi}", safe="")
        while len(out) < max_refs:
            try:
                payload = self._get(
                    f"/paper/{encoded_id}/references",
                    {
                        "fields": "title,year,externalIds,authors",
                        "offset": offset,
                        "limit": min(limit, max_refs - len(out)),
                    },
                )
            except requests.RequestException:
                break
            if payload.get("_not_found") or payload.get("_auth_error"):
                break
            rows = payload.get("data", []) or []
            if not rows:
                break
            out.extend(rows)
            offset += len(rows)
            if len(rows) < limit:
                break
            time.sleep(0.05)
        return out[:max_refs]
