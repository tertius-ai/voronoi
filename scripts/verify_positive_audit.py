"""Replay a complete positive-audit bundle without solving realization LPs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from voronoi.enumerate.catalog_match import verify_catalog_match_report
from voronoi.enumerate.census_engine import verify_positive_completion_witness
from voronoi.runtime import NOETHER_VERSION


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(directory: Path) -> dict[str, object]:
    summary_path = directory / "summary.json"
    summary = json.loads(summary_path.read_text())
    if summary.get("all_positives_recertified") is not True:
        raise ValueError("positive audit is incomplete")
    manifest = summary["evidence_files_sha256"]
    for name, digest in manifest.items():
        if Path(name).name != name or sha256(directory / name) != digest:
            raise ValueError(f"audit evidence digest disagrees: {name}")
    task = json.loads((directory / "catalog-task.json").read_text())
    report = json.loads((directory / "catalog-report.json").read_text())
    verify_catalog_match_report(task, report)
    sources = {entry["id"]: entry["vectors"] for entry in task["sources"]}
    if len(sources) != summary["source_count"]:
        raise ValueError("audit source count disagrees")
    seen = set()
    for name in sorted(manifest):
        if not name.startswith("realization-"):
            continue
        record = json.loads((directory / name).read_text())
        source_id = record["source_id"]
        if source_id not in sources or source_id in seen:
            raise ValueError("audit witness has an unknown or repeated source")
        verify_positive_completion_witness(
            {
                "status": "completed",
                "completed_vectors": sources[source_id],
                "realization_witness": record["source_realization_witness"],
            }
        )
        seen.add(source_id)
    if seen != set(sources):
        raise ValueError("audit does not retain a witness for every source")
    return {
        "type": "voronoi/positive-audit-replay@1",
        "summary_sha256": sha256(summary_path),
        "verifier_sha256": sha256(Path(__file__)),
        "noether_version": NOETHER_VERSION,
        "evidence_files_checked": len(manifest),
        "catalog_transports_replayed": len(report["matches"]),
        "source_gram_witnesses_replayed": len(seen),
        "negative_certificates_replayed": False,
        "global_census_complete": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_directory", type=Path)
    print(json.dumps(verify(parser.parse_args().audit_directory), indent=2))
