from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Issue:
    rule_id: str
    severity: str
    summary: str
    path: str
    line: int | None
    evidence: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunPaths:
    root: Path
    workspace: Path
    artifacts: Path
    logs: Path
    patches: Path
    trace: Path
    raw_traces: Path


@dataclass
class DoctorResult:
    run_id: str
    target_label: str
    source_dir: Path
    paths: RunPaths
    issues: list[Issue] = field(default_factory=list)
    commands: list[CommandResult] = field(default_factory=list)
    patch_path: Path | None = None
    fixed_workspace: Path | None = None
    uploaded_trace_dataset: str | None = None
    artifact_bucket: str | None = None
    pr_upload_attempted: bool = False

    @property
    def failed_issue_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity in {"error", "warning"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target_label": self.target_label,
            "source_dir": str(self.source_dir),
            "paths": {key: str(value) for key, value in asdict(self.paths).items()},
            "issues": [issue.to_dict() for issue in self.issues],
            "commands": [command.to_dict() for command in self.commands],
            "patch_path": str(self.patch_path) if self.patch_path else None,
            "fixed_workspace": str(self.fixed_workspace) if self.fixed_workspace else None,
            "uploaded_trace_dataset": self.uploaded_trace_dataset,
            "artifact_bucket": self.artifact_bucket,
            "pr_upload_attempted": self.pr_upload_attempted,
        }
