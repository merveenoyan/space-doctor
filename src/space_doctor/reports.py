from __future__ import annotations

import json
from pathlib import Path

from .models import DoctorResult, Issue


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_report(result: DoctorResult) -> Path:
    path = result.paths.artifacts / "report.md"
    lines = [
        f"# Space Doctor Report: {result.target_label}",
        "",
        f"- Run ID: `{result.run_id}`",
        f"- Workspace: `{result.paths.workspace}`",
        f"- Issues: {len(result.issues)}",
        f"- Patch: `{result.patch_path}`" if result.patch_path else "- Patch: none generated",
        "",
        "## Findings",
        "",
    ]
    if not result.issues:
        lines.append("No issues found by the static analyzer.")
    else:
        for issue in result.issues:
            lines.extend(format_issue(issue))
    lines.extend(
        [
            "",
            "## Commands",
            "",
        ]
    )
    if not result.commands:
        lines.append("No external commands were run.")
    else:
        for command in result.commands:
            lines.append(f"- `{shell_join(command.command)}` -> {command.returncode}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_postmortem(result: DoctorResult) -> Path:
    path = result.paths.artifacts / "postmortem.md"
    top_errors = [issue for issue in result.issues if issue.severity == "error"]
    top_warnings = [issue for issue in result.issues if issue.severity == "warning"]
    lines = [
        f"# Postmortem: {result.target_label}",
        "",
        "## What happened",
        "",
        "Space Doctor inspected the Space source, ran local reproducibility checks, and generated a traceable artifact bundle.",
        "",
        "## Impact",
        "",
        summarize_impact(top_errors, top_warnings),
        "",
        "## Root causes",
        "",
    ]
    if result.issues:
        for issue in result.issues[:6]:
            lines.append(f"- `{issue.rule_id}`: {issue.summary}")
    else:
        lines.append("- No root cause was identified by the static checks.")
    lines.extend(
        [
            "",
            "## Fix",
            "",
            "Apply the suggested patch if it matches the target Space, then run the local or HF Job reproduction command again.",
            "",
            "## Handoff",
            "",
            f"- Compact trace: `{result.paths.trace}`",
            f"- Native agent traces copied to: `{result.paths.raw_traces}`",
            f"- Artifact directory: `{result.paths.artifacts}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_handoff_prompt(result: DoctorResult, space_id: str | None = None) -> Path:
    path = result.paths.artifacts / "handoff_prompt.md"
    issues = "\n".join(f"- {issue.severity.upper()} `{issue.rule_id}` at {issue.path}:{issue.line}: {issue.summary}" for issue in result.issues)
    fixed_app = (result.fixed_workspace / "app.py") if result.fixed_workspace else None
    if space_id and fixed_app:
        push_block = (
            f"5. **Push the fix back to the Space.** When the user authorizes pushing (e.g. \"push it\", \"yes push\", \"ship it\", or any prior `--push`/`--create-pr` flag in the run), execute the command immediately. Do NOT re-prompt — the handoff itself is the authorization.\n"
            f"   - PR (recommended): `space-doctor run --space-id {space_id} --apply-known-fixes --create-pr --push`\n"
            f"   - Direct push to `main`: `hf upload {space_id} {fixed_app} app.py --type space --commit-message \"space-doctor run {result.run_id}\"`\n"
        )
    elif space_id:
        push_block = (
            f"5. **Push the fix back to the Space.** When the user authorizes pushing, execute immediately without re-prompting.\n"
            f"   - PR (recommended): `space-doctor run --space-id {space_id} --apply-known-fixes --create-pr --push`\n"
            f"   - Direct push to `main`: `hf upload {space_id} <fixed-app.py> app.py --type space`\n"
        )
    else:
        push_block = (
            "5. **Push the fix back to the Space.** If the original target was a Hub Space and the user authorizes pushing, run `hf upload <space_id> <fixed-app.py> app.py --type space` (or `space-doctor run --space-id <space_id> --apply-known-fixes --create-pr --push` for a PR). Execute on user authorization without re-prompting.\n"
        )
    text = f"""# Continue This Space Doctor Session

You are taking over a Space debugging run.

Target: {result.target_label}
Run ID: {result.run_id}
Workspace: {result.paths.workspace}
Artifacts: {result.paths.artifacts}
Trace JSONL: {result.paths.trace}

## Current Findings

{issues or "- No findings yet."}

## Next Actions

1. Read `report.md` and `postmortem.md`.
2. Inspect `patches/suggested.patch`.
3. If the patch is appropriate, apply it to the Space source.
4. Re-run `space-doctor run` with `--local-space-dir` pointing at the fixed source.
{push_block}6. Upload the native Codex/Claude/Pi JSONL trace to the trace dataset for the Hub viewer.

## Authorization Notes For The Next Agent

Pushing a fix to the target Space and uploading traces to a Hub dataset are pre-authorized parts of this workflow once the user explicitly asks for them in the resumed conversation. Treat phrases like "push", "ship", "yes do it", "upload it" as the green light — don't stack a second confirmation on top. If the user has not asked, default to dry-run (do not push). The point is: ask once at most, then act.
"""
    path.write_text(text, encoding="utf-8")
    return path


def format_issue(issue: Issue) -> list[str]:
    location = f"{issue.path}:{issue.line}" if issue.line else issue.path
    return [
        f"### {issue.severity.upper()} `{issue.rule_id}`",
        "",
        f"- Location: `{location}`",
        f"- Summary: {issue.summary}",
        f"- Evidence: `{issue.evidence}`",
        f"- Recommendation: {issue.recommendation}",
        "",
    ]


def summarize_impact(errors: list[Issue], warnings: list[Issue]) -> str:
    if errors:
        return f"{len(errors)} error-level issue(s) may prevent the Space from serving reliably."
    if warnings:
        return f"{len(warnings)} warning-level issue(s) may cause bad UX, slow startup, or fragile inference."
    return "No user-facing impact was detected by the current checks."


def shell_join(command: list[str]) -> str:
    return " ".join(command)
