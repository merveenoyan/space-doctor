from __future__ import annotations

import argparse
import json
from pathlib import Path

from .doctor import RunConfig, run_doctor


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_command(args)
    if args.command == "resume":
        return resume_command(args)
    if args.command == "asset-factory-steps":
        return asset_factory_steps_command()
    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="space-doctor")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="Inspect, reproduce, patch, and package a Space debugging run.")
    target = run.add_mutually_exclusive_group(required=True)
    target.add_argument("--space-id", help="HF Space repo id, e.g. username/my-space.")
    target.add_argument("--local-space-dir", type=Path, help="Local Space source directory.")
    run.add_argument("--out-dir", type=Path, default=Path("runs"))
    run.add_argument("--local-smoke", action="store_true", help="Run python app.py with a timeout.")
    run.add_argument("--smoke-timeout", type=int, default=12)
    run.add_argument("--apply-known-fixes", action="store_true", help="Write a fixed-space copy with safe known fixes.")
    run.add_argument("--create-pr", action="store_true", help="Upload the fixed-space copy as a Hub PR.")
    run.add_argument(
        "--artifact-bucket",
        help="HF bucket id for artifact sync, e.g. merve/space-doctor-artifacts. Defaults to <hf-user>/space-doctor-artifacts.",
    )
    run.add_argument(
        "--no-bucket-push",
        action="store_true",
        help="Skip the default artifact bucket sync (e.g. for offline or test runs).",
    )
    run.add_argument(
        "--no-fetch-logs",
        action="store_true",
        help="Skip fetching live build/run logs via `hf spaces logs` (default-on for --space-id).",
    )
    run.add_argument("--trace-dataset", help="HF dataset id for native agent traces.")
    run.add_argument("--agent-session-file", type=Path, help="Native Codex, Claude Code, or Pi session JSONL to copy/upload.")
    run.add_argument("--copy-latest-codex-trace", action="store_true", help="Copy newest ~/.codex/sessions JSONL.")
    run.add_argument("--run-hf-job", action="store_true", help="Submit a small HF Job reproduction check.")
    run.add_argument("--hf-job-flavor", default="cpu-basic")
    run.add_argument("--push", action="store_true", help="Actually upload traces and create PR (bucket sync runs by default unless --no-bucket-push).")
    run.add_argument("--fail-on-error", action="store_true", help="Exit 2 if error-level issues are found.")

    resume = subparsers.add_parser("resume", help="Summarize a Space Doctor event trace for teammate handoff.")
    resume.add_argument("trace", type=Path)

    subparsers.add_parser("asset-factory-steps", help="Print the multimodal asset factory runbook.")
    return parser


def run_command(args: argparse.Namespace) -> int:
    result = run_doctor(
        RunConfig(
            space_id=args.space_id,
            local_space_dir=args.local_space_dir,
            out_dir=args.out_dir,
            run_local_smoke=args.local_smoke,
            smoke_timeout=args.smoke_timeout,
            apply_known_fixes=args.apply_known_fixes,
            create_pr=args.create_pr,
            artifact_bucket=args.artifact_bucket,
            trace_dataset=args.trace_dataset,
            agent_session_file=args.agent_session_file,
            copy_latest_codex_trace=args.copy_latest_codex_trace,
            run_hf_job=args.run_hf_job,
            hf_job_flavor=args.hf_job_flavor,
            dry_run_uploads=not args.push,
            dry_run_bucket=args.no_bucket_push,
            fetch_space_logs=not args.no_fetch_logs,
        )
    )
    print(f"Space Doctor run complete: {result.run_id}")
    print(f"Artifacts: {result.paths.artifacts}")
    print(f"Report: {result.paths.artifacts / 'report.md'}")
    if result.patch_path:
        print(f"Suggested patch: {result.patch_path}")
    if result.artifact_bucket and not args.no_bucket_push:
        print(f"Bucket: hf://buckets/{result.artifact_bucket}/{result.run_id}")
    if not args.push:
        print("Trace/PR upload steps were dry-run only. See upload_commands.md.")
    if args.fail_on_error and any(issue.severity == "error" for issue in result.issues):
        return 2
    return 0


def resume_command(args: argparse.Namespace) -> int:
    events = []
    for line in args.trace.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    if not events:
        print("No events found.")
        return 1
    run_id = events[0].get("run_id")
    target = next((event["payload"].get("target") for event in events if event.get("event") == "run_started"), "unknown")
    analysis = next((event for event in reversed(events) if event.get("event") == "analysis_finished"), None)
    print(f"Run: {run_id}")
    print(f"Target: {target}")
    if analysis:
        payload = analysis.get("payload", {})
        print(f"Issues: {payload.get('issue_count', 0)}")
        for issue in payload.get("issues", [])[:8]:
            print(f"- {issue['severity'].upper()} {issue['rule_id']} {issue['path']}:{issue.get('line')}: {issue['summary']}")
    print("\nNext: open report.md, inspect patches/suggested.patch, then rerun Space Doctor on the fixed copy.")
    return 0


def asset_factory_steps_command() -> int:
    doc = Path(__file__).resolve().parents[2] / "docs" / "multimodal-asset-factory.md"
    if doc.exists():
        print(doc.read_text(encoding="utf-8"))
    else:
        print("See docs/multimodal-asset-factory.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
