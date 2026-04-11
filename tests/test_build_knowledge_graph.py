"""Tests for knowledge-graph provenance snapshot outputs."""

import json
import re

from src.build_knowledge_graph import write_provenance_snapshot


def test_write_provenance_snapshot_writes_stable_and_timestamped_files(tmp_path) -> None:
    out_root = tmp_path / "outputs"
    (out_root / "raw").mkdir(parents=True)
    (out_root / "normalized").mkdir(parents=True)
    (out_root / "graph").mkdir(parents=True)
    (out_root / "explorer").mkdir(parents=True)

    write_provenance_snapshot(tmp_path, "outputs")

    provenance_dir = out_root / "provenance"
    stable = provenance_dir / "retrieval_snapshot.json"
    assert stable.exists()

    stamped = [p.name for p in provenance_dir.glob("retrieval_snapshot_*.json")]
    assert len(stamped) == 1
    assert re.match(r"^retrieval_snapshot_\d{8}T\d{6}Z\.json$", stamped[0])

    payload = json.loads(stable.read_text(encoding="utf-8"))
    assert re.match(r"^\d{8}T\d{6}Z$", payload.get("snapshot_id_utc", ""))
