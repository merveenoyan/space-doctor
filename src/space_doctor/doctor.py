from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .analyzers import analyze_space
from .models import CommandResult, DoctorResult, RunPaths
from .patches import apply_known_fixes, build_suggested_patch
from .reports import write_handoff_prompt, write_json, write_postmortem, write_report
from .shell import run_command
from .trace import TraceWriter, copy_agent_session_trace, latest_codex_session


@dataclass(frozen=True)
class RunConfig:
    space_id: str | None = None
    local_space_dir: Path | None = None
    out_dir: Path = Path("runs")
    run_local_smoke: bool = False
    smoke_timeout: int = 12
    apply_known_fixes: bool = False
    create_pr: bool = False
    artifact_bucket: str | None = None
    trace_dataset: str | None = None
    agent_session_file: Path | None = None
    copy_latest_codex_trace: bool = False
    run_hf_job: bool = False
    hf_job_flavor: str = "cpu-basic"
    dry_run_uploads: bool = True
    dry_run_bucket: bool = False


def run_doctor(config: RunConfig) -> DoctorResult:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    target_label = config.space_id or str(config.local_space_dir)
    paths = make_run_paths(config.out_dir, run_id)
    trace = TraceWriter(paths.trace, run_id=run_id)
    trace.write("run_started", target=target_label)

    commands: list[CommandResult] = []
    source_dir, inspect_commands = prepare_workspace(config, paths, trace)
    commands.extend(inspect_commands)

    compile_result = run_command(["python3", "-m", "py_compile", str(source_dir / "app.py")], timeout=20)
    commands.append(compile_result)
    write_command_log(paths.logs / "py_compile.log", compile_result)
    trace.write("local_compile_finished", returncode=compile_result.returncode)

    if config.run_local_smoke:
        smoke = run_command(["python3", "app.py"], cwd=source_dir, timeout=config.smoke_timeout)
        commands.append(smoke)
        write_command_log(paths.logs / "local_smoke.log", smoke)
        trace.write("local_smoke_finished", returncode=smoke.returncode)

    if config.run_hf_job:
        job_command = build_hf_job_command(source_dir, config.hf_job_flavor)
        job = run_command(job_command, cwd=source_dir, timeout=60)
        commands.append(job)
        write_command_log(paths.logs / "hf_job_submission.log", job)
        trace.write("hf_job_submission_finished", command=job.command, returncode=job.returncode)
    else:
        (paths.artifacts / "hf_job_repro.md").write_text(build_hf_job_runbook(source_dir, config.hf_job_flavor), encoding="utf-8")

    artifact_bucket = resolve_artifact_bucket(config, trace)

    issues = analyze_space(source_dir)
    trace.write("analysis_finished", issue_count=len(issues), issues=[issue.to_dict() for issue in issues])

    patch_text = build_suggested_patch(source_dir)
    patch_path = None
    if patch_text:
        patch_path = paths.patches / "suggested.patch"
        patch_path.write_text(patch_text, encoding="utf-8")
        trace.write("patch_suggested", patch_path=str(patch_path))

    fixed_workspace = None
    if config.apply_known_fixes:
        fixed_workspace = paths.root / "fixed-space"
        shutil.copytree(source_dir, fixed_workspace, dirs_exist_ok=True)
        changed = apply_known_fixes(fixed_workspace)
        trace.write("known_fixes_applied", changed_files=[str(path) for path in changed])

    result = DoctorResult(
        run_id=run_id,
        target_label=target_label or "unknown",
        source_dir=source_dir,
        paths=paths,
        issues=issues,
        commands=commands,
        patch_path=patch_path,
        fixed_workspace=fixed_workspace,
        artifact_bucket=artifact_bucket,
    )

    write_json(paths.artifacts / "diagnostics.json", result.to_dict())
    write_report(result)
    write_postmortem(result)
    write_handoff_prompt(result, space_id=config.space_id)
    write_upload_runbook(result, config)

    if config.agent_session_file:
        copied = copy_agent_session_trace(config.agent_session_file.expanduser(), paths.raw_traces)
        trace.write("native_agent_trace_copied", source=str(config.agent_session_file), destination=str(copied))
    if config.copy_latest_codex_trace:
        latest = latest_codex_session()
        if latest:
            copied = copy_agent_session_trace(latest, paths.raw_traces)
            trace.write("latest_codex_trace_copied", source=str(latest), destination=str(copied))
        else:
            trace.write("latest_codex_trace_missing")

    if artifact_bucket:
        sync_artifacts(result, config, trace)
    if config.trace_dataset:
        upload_trace_dataset(result, config, trace)
    if config.create_pr:
        create_space_pr(result, config, trace)

    trace.write("run_finished", artifact_dir=str(paths.artifacts), issue_count=len(issues))
    return result


def make_run_paths(out_dir: Path, run_id: str) -> RunPaths:
    root = out_dir / run_id
    paths = RunPaths(
        root=root,
        workspace=root / "workspace",
        artifacts=root / "artifacts",
        logs=root / "artifacts" / "logs",
        patches=root / "artifacts" / "patches",
        trace=root / "artifacts" / "space_doctor_events.jsonl",
        raw_traces=root / "artifacts" / "native-agent-traces",
    )
    for path in [paths.workspace, paths.artifacts, paths.logs, paths.patches, paths.raw_traces]:
        path.mkdir(parents=True, exist_ok=True)
    return paths


def prepare_workspace(
    config: RunConfig,
    paths: RunPaths,
    trace: TraceWriter,
) -> tuple[Path, list[CommandResult]]:
    commands: list[CommandResult] = []
    if config.local_space_dir:
        source = config.local_space_dir.expanduser().resolve()
        workspace = paths.workspace / source.name
        shutil.copytree(source, workspace, dirs_exist_ok=True)
        trace.write("local_space_copied", source=str(source), workspace=str(workspace))
        return workspace, commands

    if not config.space_id:
        raise ValueError("Provide either --space-id or --local-space-dir.")

    info = run_command(["hf", "spaces", "info", config.space_id, "--format", "json"], timeout=60)
    commands.append(info)
    write_command_log(paths.logs / "hf_space_info.log", info)
    if info.stdout.strip():
        (paths.artifacts / "space_info.json").write_text(info.stdout, encoding="utf-8")
    trace.write("hf_space_info_finished", returncode=info.returncode)

    workspace = paths.workspace / slug(config.space_id)
    download = run_command(
        ["hf", "download", config.space_id, "--type", "space", "--local-dir", str(workspace)],
        timeout=300,
    )
    commands.append(download)
    write_command_log(paths.logs / "hf_download.log", download)
    trace.write("hf_space_download_finished", returncode=download.returncode, workspace=str(workspace))
    return workspace, commands


def write_command_log(path: Path, result: CommandResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "command": result.command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def build_hf_job_command(source_dir: Path, flavor: str) -> list[str]:
    script = source_dir / "space_doctor_hf_job_repro.py"
    script.write_text(
        """# /// script
# dependencies = ["gradio", "huggingface_hub"]
# ///

from pathlib import Path
import py_compile

app = Path("app.py")
print(f"Checking {app.resolve()}")
py_compile.compile(str(app), doraise=True)
print("py_compile OK")
""",
        encoding="utf-8",
    )
    return ["hf", "jobs", "uv", "run", str(script), "--flavor", flavor, "--timeout", "10m"]


def build_hf_job_runbook(source_dir: Path, flavor: str) -> str:
    return f"""# HF Job Reproduction

Space Doctor did not submit a remote job for this run. To reproduce on HF Jobs:

```bash
cd {source_dir}
space-doctor run --local-space-dir {source_dir} --run-hf-job --hf-job-flavor {flavor}
```

For Spaces that need Hub access, make sure your job receives `HF_TOKEN` as a secret.
"""


def write_upload_runbook(result: DoctorResult, config: RunConfig) -> None:
    lines = [
        "# Upload And Handoff Commands",
        "",
        "Run these when the dry run looks good.",
        "",
    ]
    bucket = result.artifact_bucket
    if bucket:
        bucket_status = "Already synced." if not config.dry_run_bucket else "Skipped via --no-bucket-push; rerun manually with:"
        lines.extend(
            [
                "## Artifact Bucket",
                "",
                bucket_status,
                "",
                f"```bash\nhf buckets create {bucket} --exist-ok\nhf buckets sync {result.paths.artifacts} hf://buckets/{bucket}/{result.run_id} --delete\n```",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Artifact Bucket",
                "",
                "Bucket sync skipped (no bucket resolved). Pass --artifact-bucket or run `hf auth login`, then:",
                "",
                "```bash\nhf buckets create <namespace>/<bucket-name> --exist-ok\nhf buckets sync "
                f"{result.paths.artifacts} hf://buckets/<namespace>/<bucket-name>/{result.run_id} --delete\n```",
                "",
            ]
        )
    if config.trace_dataset:
        lines.extend(
            [
                "## Trace Dataset",
                "",
                f"```bash\nhf repos create {config.trace_dataset} --type dataset --exist-ok\nhf upload {config.trace_dataset} {result.paths.raw_traces} data --type dataset\nhf upload {config.trace_dataset} {result.paths.trace} data/{result.paths.trace.name} --type dataset\n```",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Trace Dataset",
                "",
                "```bash\nhf repos create <namespace>/<trace-dataset> --type dataset --exist-ok\nhf upload <namespace>/<trace-dataset> "
                f"{result.paths.raw_traces} data --type dataset\n```",
                "",
            ]
        )
    (result.paths.artifacts / "upload_commands.md").write_text("\n".join(lines), encoding="utf-8")


def sync_artifacts(result: DoctorResult, config: RunConfig, trace: TraceWriter) -> None:
    bucket = result.artifact_bucket
    if not bucket:
        trace.write("artifact_sync_skipped_no_bucket")
        return
    if config.dry_run_bucket:
        trace.write("artifact_sync_skipped_dry_run", bucket=bucket)
        return
    create = run_command(["hf", "buckets", "create", bucket, "--exist-ok"], timeout=60)
    sync = run_command(
        [
            "hf",
            "buckets",
            "sync",
            str(result.paths.artifacts),
            f"hf://buckets/{bucket}/{result.run_id}",
            "--delete",
        ],
        timeout=300,
    )
    result.commands.extend([create, sync])
    write_command_log(result.paths.logs / "hf_bucket_create.log", create)
    write_command_log(result.paths.logs / "hf_bucket_sync.log", sync)
    trace.write("artifact_sync_finished", bucket=bucket, returncode=sync.returncode)


def resolve_artifact_bucket(config: RunConfig, trace: TraceWriter) -> str | None:
    if config.artifact_bucket:
        trace.write("artifact_bucket_resolved", bucket=config.artifact_bucket, source="explicit")
        return config.artifact_bucket
    if config.dry_run_bucket:
        return None
    whoami = run_command(["hf", "auth", "whoami"], timeout=20)
    if whoami.returncode != 0:
        trace.write("artifact_bucket_resolution_failed", reason="hf auth whoami failed", stderr=whoami.stderr)
        return None
    user = _parse_whoami_user(whoami.stdout)
    if not user:
        trace.write("artifact_bucket_resolution_failed", reason="could not parse user", stdout=whoami.stdout)
        return None
    bucket = f"{user}/space-doctor-artifacts"
    trace.write("artifact_bucket_resolved", bucket=bucket, source="hf-auth-whoami")
    return bucket


def _parse_whoami_user(stdout: str) -> str | None:
    for token in stdout.split():
        if token.startswith("user="):
            return token.split("=", 1)[1] or None
    return None


def upload_trace_dataset(result: DoctorResult, config: RunConfig, trace: TraceWriter) -> None:
    if config.dry_run_uploads:
        trace.write("trace_upload_skipped_dry_run", dataset=config.trace_dataset)
        return
    assert config.trace_dataset
    create = run_command(["hf", "repos", "create", config.trace_dataset, "--type", "dataset", "--exist-ok"], timeout=60)
    upload_raw = run_command(
        ["hf", "upload", config.trace_dataset, str(result.paths.raw_traces), "data", "--type", "dataset"],
        timeout=300,
    )
    upload_events = run_command(
        [
            "hf",
            "upload",
            config.trace_dataset,
            str(result.paths.trace),
            f"data/{result.paths.trace.name}",
            "--type",
            "dataset",
        ],
        timeout=300,
    )
    result.commands.extend([create, upload_raw, upload_events])
    result.uploaded_trace_dataset = config.trace_dataset
    write_command_log(result.paths.logs / "hf_trace_dataset_create.log", create)
    write_command_log(result.paths.logs / "hf_trace_dataset_upload_raw.log", upload_raw)
    write_command_log(result.paths.logs / "hf_trace_dataset_upload_events.log", upload_events)
    trace.write("trace_upload_finished", dataset=config.trace_dataset, returncode=upload_raw.returncode)


def create_space_pr(result: DoctorResult, config: RunConfig, trace: TraceWriter) -> None:
    if not config.space_id:
        trace.write("space_pr_skipped_no_space_id")
        return
    if not result.fixed_workspace:
        trace.write("space_pr_skipped_no_fixed_workspace")
        return
    result.pr_upload_attempted = True
    if config.dry_run_uploads:
        trace.write("space_pr_skipped_dry_run", space_id=config.space_id)
        return
    upload = run_command(
        [
            "hf",
            "upload",
            config.space_id,
            str(result.fixed_workspace),
            ".",
            "--type",
            "space",
            "--create-pr",
            "--commit-message",
            "Fix Space startup and inference robustness",
        ],
        timeout=300,
    )
    result.commands.append(upload)
    write_command_log(result.paths.logs / "hf_space_pr_upload.log", upload)
    trace.write("space_pr_upload_finished", returncode=upload.returncode)


def slug(value: str) -> str:
    return value.replace("/", "__").replace(":", "_")


def ensure_hf_token_hint() -> str:
    return "HF_TOKEN is set." if os.getenv("HF_TOKEN") else "HF_TOKEN is not set; authenticated hf CLI login may still work locally."
