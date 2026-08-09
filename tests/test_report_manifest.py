from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from repoevidence.report_manifest import (
    REPORT_MANIFEST_RELATIVE_PATH,
    ReportConsumedArtifact,
    ReportFreshness,
    ReportLifecycle,
    assess_report,
    build_report_manifest,
    write_report_manifest,
)

NOW = datetime(2026, 8, 9, 14, 32, tzinfo=timezone.utc)


def _write(root: Path, relative: str, value: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _manifest(root: Path, language: str = "en") -> None:
    output = root / ".repoevidence/report/index.html"
    manifest = build_report_manifest(
        root,
        generated_at=NOW,
        language=language,
        output_path=output,
    )
    write_report_manifest(root, manifest)


def test_manifest_records_versioned_inputs_and_deterministic_output(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, ".repoevidence/evidence.json", "source")
    _write(root, ".repoevidence/report/index.html", "report")

    manifest = build_report_manifest(
        root,
        generated_at=NOW,
        language="zh-CN",
        output_path=root / ".repoevidence/report/index.html",
    )
    path = write_report_manifest(root, manifest)

    assert path == root / REPORT_MANIFEST_RELATIVE_PATH
    payload = path.read_text(encoding="utf-8")
    assert '"schema_version": 1' in payload
    assert '"language": "zh-CN"' in payload
    assert '"output_path": ".repoevidence/report/index.html"' in payload
    assert any(
        item.path == ".repoevidence/evidence.json" and item.sha256
        for item in manifest.consumed_artifacts
    )
    assert any(
        item.path == ".repoevidence/verification/mysql.json" and item.sha256 is None
        for item in manifest.consumed_artifacts
    )


def test_manifest_assessment_uses_hashes_not_mtime(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, ".repoevidence/evidence.json", "source")
    _write(root, ".repoevidence/report/index.html", "report")
    _manifest(root)

    fresh = assess_report(root, language="en")
    assert fresh.lifecycle is ReportLifecycle.VALID
    assert fresh.freshness is ReportFreshness.FRESH

    _write(root, ".repoevidence/evidence.json", "changed source")
    stale = assess_report(root, language="en")
    assert stale.freshness is ReportFreshness.STALE
    assert stale.reason_codes == ("input_hash_mismatch",)

    _write(root, ".repoevidence/evidence.json", "source")
    _write(root, ".repoevidence/report/index.html", "changed report")
    output_stale = assess_report(root, language="en")
    assert output_stale.freshness is ReportFreshness.STALE
    assert output_stale.reason_codes == ("output_hash_mismatch",)


def test_manifest_rejects_paths_outside_the_fixed_artifact_contract(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, ".repoevidence/evidence.json", "source")
    _write(root, ".repoevidence/report/index.html", "report")
    manifest = build_report_manifest(
        root,
        generated_at=NOW,
        language="en",
        output_path=root / ".repoevidence/report/index.html",
    ).model_copy(
        update={
            "consumed_artifacts": [
                ReportConsumedArtifact(path="../../outside.json", sha256=None)
            ],
            "output_path": "../../outside.html",
        }
    )
    write_report_manifest(root, manifest)

    assessment = assess_report(root, language="en")

    assert assessment.lifecycle is ReportLifecycle.CORRUPT
    assert assessment.freshness is ReportFreshness.UNKNOWN
    assert assessment.reason_codes == ("manifest_unsafe_path", "manifest_output_mismatch")

    complete_manifest = build_report_manifest(
        root,
        generated_at=NOW,
        language="en",
        output_path=root / ".repoevidence/report/index.html",
    ).model_copy(update={"consumed_artifacts": []})
    write_report_manifest(root, complete_manifest)
    incomplete = assess_report(root, language="en")
    assert incomplete.lifecycle is ReportLifecycle.CORRUPT
    assert incomplete.reason_codes == ("manifest_unsafe_path",)


def test_old_report_has_unknown_freshness_and_language_difference_is_explicit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, ".repoevidence/report/index.html", "legacy report")

    legacy = assess_report(root, language="zh-CN")

    assert legacy.lifecycle is ReportLifecycle.VALID
    assert legacy.freshness is ReportFreshness.UNKNOWN
    assert legacy.reason_codes == ("manifest_missing",)

    _write(root, ".repoevidence/evidence.json", "source")
    _manifest(root, language="en")
    language_mismatch = assess_report(root, language="zh-CN")
    assert language_mismatch.freshness is ReportFreshness.FRESH
    assert language_mismatch.language_matches is False
    assert language_mismatch.reason_codes == ("language_mismatch",)


def test_corrupt_manifest_is_not_deleted_or_treated_as_fresh(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    report = _write(root, ".repoevidence/report/index.html", "report")
    manifest_path = root / REPORT_MANIFEST_RELATIVE_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{broken", encoding="utf-8")

    result = assess_report(root, language="en")

    assert result.lifecycle is ReportLifecycle.CORRUPT
    assert result.freshness is ReportFreshness.UNKNOWN
    assert manifest_path.read_text(encoding="utf-8") == "{broken"
    assert report.is_file()
