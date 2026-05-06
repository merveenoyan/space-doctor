# Space Doctor

Space Doctor is an end-to-end Hugging Face agent demo:

1. Inspect a Gradio Space with `hf`.
2. Reproduce failures locally or with an HF Job.
3. Diagnose common Gradio / ZeroGPU issues.
4. Store logs, patches, reports, and postmortems as artifacts.
5. Copy native Codex / Claude Code / Pi traces for upload to a Hub dataset.
6. Optionally sync artifacts to an HF bucket and open a Space PR.
7. Hand off the trace and artifact bundle so another agent can continue.

The Hub trace viewer auto-detects native agent session JSONL files. Space Doctor
also writes a compact `space_doctor_events.jsonl`, but the native agent session
is the important file to upload for the trace viewer.

## Quickstart

Run the included broken sample. Artifacts are pushed to a Hub bucket by default
(`<hf-user>/space-doctor-artifacts`); add `--no-bucket-push` for a fully offline
run.

```bash
cd /Users/mervenoyan/space-doctor
PYTHONPATH=src python3 -m space_doctor.cli run \
  --local-space-dir examples/broken-llava-space \
  --out-dir runs \
  --apply-known-fixes \
  --copy-latest-codex-trace
```

Inspect the output:

```bash
open runs/<run-id>/artifacts/report.md
open runs/<run-id>/artifacts/postmortem.md
open runs/<run-id>/artifacts/patches/suggested.patch
```

Use the handoff view:

```bash
PYTHONPATH=src python3 -m space_doctor.cli resume runs/<run-id>/artifacts/space_doctor_events.jsonl
```

## Debug A Real Space

Artifact bucket sync is on by default. Trace-dataset uploads and Space PR
creation are still gated behind `--push`.

```bash
PYTHONPATH=src python3 -m space_doctor.cli run \
  --space-id <namespace>/<space-name> \
  --out-dir runs \
  --apply-known-fixes \
  --trace-dataset <namespace>/space-doctor-traces \
  --copy-latest-codex-trace
```

Push the trace dataset and open a Space PR as well:

```bash
PYTHONPATH=src python3 -m space_doctor.cli run \
  --space-id <namespace>/<space-name> \
  --out-dir runs \
  --apply-known-fixes \
  --create-pr \
  --artifact-bucket <namespace>/space-doctor-artifacts \
  --trace-dataset <namespace>/space-doctor-traces \
  --copy-latest-codex-trace \
  --push
```

## HF Job Reproduction

Submit a small remote check:

```bash
PYTHONPATH=src python3 -m space_doctor.cli run \
  --local-space-dir examples/broken-llava-space \
  --run-hf-job \
  --hf-job-flavor cpu-basic
```

For Spaces requiring Hub access, pass `HF_TOKEN` to the job as a secret when you
adapt the generated reproduction script.

## Multimodal Asset Factory

The companion runbook is in `docs/multimodal-asset-factory.md`.

```bash
PYTHONPATH=src python3 -m space_doctor.cli asset-factory-steps
```
