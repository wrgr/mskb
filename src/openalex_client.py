
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests


class OpenAlexClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        per_page: int = 200,
        timeout: int = 60,
        cache_dir: Optional[Path] = None,
        max_retries: int = 4,
        max_retry_sleep_s: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.per_page = per_page
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
        self.max_retry_sleep_s = max(1.0, float(max_retry_sleep_s))
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"mskb/0.1 ({email})"})

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
        params["mailto"] = self.email
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
            if r.status_code == 404:
                payload = {"_not_found": True}
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

    def search_works(self, query: str, max_results: int = 500, filter_expr: str = "") -> List[Dict]:
        results = []
        cursor = "*"
        while len(results) < max_results:
            params = {"search": query, "per-page": min(self.per_page, max_results - len(results)), "cursor": cursor}
            if filter_expr:
                params["filter"] = filter_expr
            try:
                payload = self._get(
                    "/works",
                    params,
                )
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 400:
                    # Malformed query (e.g. journal-name fragment extracted as title); skip.
                    break
                raise
            page_results = payload.get("results", [])
            results.extend(page_results)
            meta = payload.get("meta", {})
            cursor = meta.get("next_cursor")
            if not cursor or not page_results:
                break
            time.sleep(0.05)
        return results[:max_results]

    def get_work_by_doi(self, doi: str) -> Optional[Dict]:
        doi = doi.strip()
        if not doi:
            return None
        try:
            payload = self._get(f"/works/https://doi.org/{doi}")
            if payload.get("_not_found"):
                return None
            return payload
        except requests.HTTPError:
            return None

    def get_work_by_openalex_id(self, work_id: str) -> Optional[Dict]:
        work_id = work_id.strip()
        if not work_id:
            return None
        if not work_id.startswith("https://openalex.org/"):
            work_id = f"https://openalex.org/{work_id}"
        try:
            payload = self._get(f"/works/{work_id}")
            if payload.get("_not_found"):
                return None
            return payload
        except requests.HTTPError:
            return None

    def get_citing_works(self, openalex_id: str, max_pages: int = 3) -> List[Dict]:
        if openalex_id.startswith("https://openalex.org/"):
            openalex_id = openalex_id.split("/")[-1]
        results = []
        cursor = "*"
        pages = 0
        while pages < max_pages:
            payload = self._get(
                "/works",
                {"filter": f"cites:{openalex_id}", "per-page": self.per_page, "cursor": cursor},
            )
            page_results = payload.get("results", [])
            results.extend(page_results)
            meta = payload.get("meta", {})
            cursor = meta.get("next_cursor")
            if not cursor or not page_results:
                break
            pages += 1
            time.sleep(0.05)
        return results

    def get_multiple_works(self, ids: List[str]) -> List[Dict]:
        ids = [x.split("/")[-1] if x.startswith("https://openalex.org/") else x for x in ids if x]
        if not ids:
            return []
        chunks = [ids[i:i + 50] for i in range(0, len(ids), 50)]
        out = []
        for chunk in chunks:
            payload = self._get("/works", {"filter": f"openalex:{'|'.join(chunk)}", "per-page": len(chunk)})
            out.extend(payload.get("results", []))
            time.sleep(0.05)
        return out
