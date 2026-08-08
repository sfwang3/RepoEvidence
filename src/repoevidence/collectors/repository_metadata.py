import subprocess
from pathlib import Path
from typing import Any

from repoevidence.collectors.base import Collector
from repoevidence.models import CollectorResult, Evidence, Fact


class RepositoryMetadataCollector(Collector):
    name = "repository_metadata"

    _tracked_files = {
        "pom_xml": "pom.xml",
        "build_gradle": "build.gradle",
        "package_json": "package.json",
        "docker_compose_yml": "docker-compose.yml",
    }

    def collect(self, repo_root: Path) -> CollectorResult:
        root = repo_root.resolve()
        result = CollectorResult()

        result.evidence.append(
            Evidence(
                id="ev.repository.root",
                kind="path",
                source="scan input",
                value=str(root),
            )
        )
        result.facts.append(
            Fact(
                id="fact.repository.root",
                name="Repository root",
                value=str(root),
                status="verified",
                evidence_ids=["ev.repository.root"],
            )
        )

        git_check = self._run_git(root, ["rev-parse", "--is-inside-work-tree"])
        result.evidence.append(
            Evidence(
                id="ev.git.repository_check",
                kind="command_output",
                source="git rev-parse --is-inside-work-tree",
                value=git_check,
            )
        )
        is_git_repo = git_check["returncode"] == 0 and git_check["stdout"].strip() == "true"
        result.facts.append(
            Fact(
                id="fact.git.repository_exists",
                name="Git repository exists",
                value=is_git_repo,
                status="verified",
                evidence_ids=["ev.git.repository_check"],
            )
        )

        if is_git_repo:
            self._collect_git_fact(
                result,
                root,
                fact_id="fact.git.head_commit",
                name="HEAD commit",
                args=["rev-parse", "HEAD"],
                source="git rev-parse HEAD",
            )
            self._collect_git_fact(
                result,
                root,
                fact_id="fact.git.current_branch",
                name="Current branch",
                args=["branch", "--show-current"],
                source="git branch --show-current",
            )
        else:
            result.warnings.append(
                f"{root} is not a Git repository; HEAD and branch are unavailable."
            )
            for fact_id, name in (
                ("fact.git.head_commit", "HEAD commit"),
                ("fact.git.current_branch", "Current branch"),
            ):
                self._record_unavailable_git_fact(
                    result,
                    fact_id=fact_id,
                    name=name,
                    source="git metadata",
                    reason="not a Git repository",
                )

        for key, relative_path in self._tracked_files.items():
            path = root / relative_path
            evidence_id = f"ev.file.{key}"
            exists = path.is_file()
            result.evidence.append(
                Evidence(
                    id=evidence_id,
                    kind="file_exists",
                    source=str(path),
                    value={"path": str(path), "exists": exists, "is_file": exists},
                )
            )
            result.facts.append(
                Fact(
                    id=f"fact.file.{key}_exists",
                    name=f"{relative_path} exists",
                    value=exists,
                    status="verified",
                    evidence_ids=[evidence_id],
                )
            )

        return result

    def _collect_git_fact(
        self,
        result: CollectorResult,
        root: Path,
        *,
        fact_id: str,
        name: str,
        args: list[str],
        source: str,
    ) -> None:
        observation = self._run_git(root, args)
        evidence_id = fact_id.replace("fact.", "ev.", 1)
        result.evidence.append(
            Evidence(
                id=evidence_id,
                kind="command_output",
                source=source,
                value=observation,
            )
        )
        value = observation["stdout"].strip() or None
        if observation["returncode"] == 0 and value is not None:
            result.facts.append(
                Fact(
                    id=fact_id,
                    name=name,
                    value=value,
                    status="verified",
                    evidence_ids=[evidence_id],
                )
            )
        else:
            result.warnings.append(f"Unable to determine {name.lower()} for {root}.")

    @staticmethod
    def _record_unavailable_git_fact(
        result: CollectorResult,
        *,
        fact_id: str,
        name: str,
        source: str,
        reason: str,
    ) -> None:
        result.evidence.append(
            Evidence(
                id=fact_id.replace("fact.", "ev.", 1),
                kind="unavailable",
                source=source,
                value={"available": False, "reason": reason},
            )
        )
        result.warnings.append(f"Unable to determine {name.lower()}: {reason}.")

    @staticmethod
    def _run_git(root: Path, args: list[str]) -> dict[str, Any]:
        command = ["git", "-C", str(root), *args]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            return {
                "command": command,
                "returncode": None,
                "stdout": "",
                "stderr": str(exc),
            }
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
