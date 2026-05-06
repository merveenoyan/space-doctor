from __future__ import annotations

import ast
import re
from pathlib import Path

from .models import Issue


SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def analyze_space(space_dir: Path) -> list[Issue]:
    issues: list[Issue] = []
    issues.extend(analyze_metadata(space_dir))
    app_file = detect_app_file(space_dir)
    if app_file is None:
        issues.append(
            Issue(
                rule_id="missing-app-file",
                severity="error",
                summary="No app.py found for the Gradio Space.",
                path=".",
                line=None,
                evidence="Expected app.py or README app_file metadata.",
                recommendation="Add app.py or set app_file in README front matter.",
            )
        )
        return sorted_issues(issues)

    issues.extend(analyze_python_file(app_file, app_file.relative_to(space_dir).as_posix()))
    return sorted_issues(issues)


def sorted_issues(issues: list[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 99), issue.path, issue.line or 0))


def detect_app_file(space_dir: Path) -> Path | None:
    metadata = parse_readme_front_matter(space_dir / "README.md")
    app_file = metadata.get("app_file")
    if app_file:
        candidate = space_dir / app_file
        if candidate.exists():
            return candidate
    candidate = space_dir / "app.py"
    if candidate.exists():
        return candidate
    return None


def analyze_metadata(space_dir: Path) -> list[Issue]:
    issues: list[Issue] = []
    readme = space_dir / "README.md"
    if not readme.exists():
        return [
            Issue(
                rule_id="missing-readme-metadata",
                severity="warning",
                summary="README.md is missing, so Space metadata cannot be checked.",
                path="README.md",
                line=None,
                evidence="README.md not found.",
                recommendation="Add README front matter with sdk: gradio and app_file.",
            )
        ]

    metadata = parse_readme_front_matter(readme)
    sdk = str(metadata.get("sdk", "")).lower()
    if sdk and sdk != "gradio":
        issues.append(
            Issue(
                rule_id="non-gradio-sdk",
                severity="warning",
                summary="Space SDK is not gradio.",
                path="README.md",
                line=front_matter_line(readme, "sdk"),
                evidence=f"sdk: {metadata.get('sdk')}",
                recommendation="For this use case, target a Gradio Space or adapt the analyzer rules.",
            )
        )
    if "sdk" not in metadata:
        issues.append(
            Issue(
                rule_id="missing-sdk-metadata",
                severity="warning",
                summary="README metadata does not declare an SDK.",
                path="README.md",
                line=None,
                evidence="No sdk key in README front matter.",
                recommendation="Add sdk: gradio so the Hub launches the Space correctly.",
            )
        )
    if "app_file" not in metadata and not (space_dir / "app.py").exists():
        issues.append(
            Issue(
                rule_id="missing-app-file-metadata",
                severity="error",
                summary="README metadata does not point to a runnable app file.",
                path="README.md",
                line=None,
                evidence="No app_file key and no app.py.",
                recommendation="Add app_file metadata or rename the entrypoint to app.py.",
            )
        )

    requirements = space_dir / "requirements.txt"
    pyproject = space_dir / "pyproject.toml"
    if not requirements.exists() and not pyproject.exists():
        issues.append(
            Issue(
                rule_id="missing-dependency-file",
                severity="warning",
                summary="No requirements.txt or pyproject.toml found.",
                path=".",
                line=None,
                evidence="Dependency manifest not found.",
                recommendation="Pin gradio, spaces, transformers, or other runtime dependencies.",
            )
        )
    else:
        dependency_text = ""
        if requirements.exists():
            dependency_text += requirements.read_text(encoding="utf-8", errors="ignore")
        if pyproject.exists():
            dependency_text += pyproject.read_text(encoding="utf-8", errors="ignore")
        if "gradio" not in dependency_text.lower():
            issues.append(
                Issue(
                    rule_id="missing-gradio-dependency",
                    severity="warning",
                    summary="Dependency manifest does not mention gradio.",
                    path="requirements.txt" if requirements.exists() else "pyproject.toml",
                    line=None,
                    evidence="No gradio dependency string found.",
                    recommendation="Add a gradio dependency that matches the Space's SDK version.",
                )
            )
    return issues


def parse_readme_front_matter(readme: Path) -> dict[str, str]:
    if not readme.exists():
        return {}
    text = readme.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("'\"")
    return metadata


def front_matter_line(readme: Path, key: str) -> int | None:
    for idx, line in enumerate(readme.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if line.startswith(f"{key}:"):
            return idx
    return None


def analyze_python_file(path: Path, display_path: str) -> list[Issue]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    issues: list[Issue] = []

    try:
        tree = ast.parse(text, filename=display_path)
    except SyntaxError as exc:
        return [
            Issue(
                rule_id="python-syntax-error",
                severity="error",
                summary="Python entrypoint has a syntax error.",
                path=display_path,
                line=exc.lineno,
                evidence=exc.msg,
                recommendation="Fix syntax before launching or running remote reproduction.",
            )
        ]

    issues.extend(find_module_level_gpu_loads(tree, lines, display_path))
    issues.extend(find_common_text_patterns(text, lines, display_path))
    return issues


def find_module_level_gpu_loads(tree: ast.AST, lines: list[str], display_path: str) -> list[Issue]:
    issues: list[Issue] = []
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        snippet = ast.get_source_segment("\n".join(lines), node) or ""
        if re.search(r"\.to\(\s*['\"]cuda", snippet) or ".cuda(" in snippet or "device_map=\"auto\"" in snippet:
            issues.append(
                Issue(
                    rule_id="module-level-gpu-load",
                    severity="warning",
                    summary="The Space performs GPU/model placement at import time.",
                    path=display_path,
                    line=getattr(node, "lineno", None),
                    evidence=first_line(snippet),
                    recommendation=(
                        "Move GPU placement or large model loading into a lazy path, ideally inside a "
                        "@spaces.GPU function for ZeroGPU Spaces."
                    ),
                )
            )
    return issues


def find_common_text_patterns(text: str, lines: list[str], display_path: str) -> list[Issue]:
    issues: list[Issue] = []
    patterns = [
        (
            "streamer-uses-processor",
            "warning",
            "TextIteratorStreamer is constructed with a processor instead of a tokenizer.",
            r"TextIteratorStreamer\(\s*processor\s*,",
            "TextIteratorStreamer expects a tokenizer-like object; use processor.tokenizer when available.",
        ),
        (
            "frame-sampling-zero-division",
            "error",
            "Video frame sampling can divide or modulo by zero.",
            r"interval\s*=\s*total_frames\s*//\s*num_frames",
            "Use max(1, total_frames // max(1, num_frames)) and handle empty videos explicitly.",
        ),
        (
            "gr-error-not-raised",
            "warning",
            "gr.Error is constructed without being raised.",
            r"^\s*gr\.Error\(",
            "Use raise gr.Error(...) so Gradio stops the event and shows the message.",
        ),
        (
            "launch-debug-true",
            "info",
            "demo.launch(debug=True) is enabled.",
            r"launch\([^)]*debug\s*=\s*True",
            "Disable debug=True before publishing if logs contain sensitive information.",
        ),
    ]
    for rule_id, severity, summary, pattern, recommendation in patterns:
        for idx, line in enumerate(lines, 1):
            if re.search(pattern, line):
                issues.append(
                    Issue(
                        rule_id=rule_id,
                        severity=severity,
                        summary=summary,
                        path=display_path,
                        line=idx,
                        evidence=line.strip(),
                        recommendation=recommendation,
                    )
                )

    if "if image is None" in text and not re.search(r"image\s*=\s*None", text):
        issues.append(
            Issue(
                rule_id="possibly-uninitialized-image",
                severity="error",
                summary="The image variable may be read before assignment.",
                path=display_path,
                line=find_line(lines, "if image is None"),
                evidence="image is checked for None without an initializer in the function.",
                recommendation="Initialize image = None before branching on uploaded files or history.",
            )
        )

    if "cv2.cvtColor(frame" in text and "if not ret" in text:
        cvt_line = find_line(lines, "cv2.cvtColor(frame")
        ret_line = find_line(lines, "if not ret")
        if cvt_line and ret_line and cvt_line < ret_line:
            issues.append(
                Issue(
                    rule_id="ret-checked-after-frame-use",
                    severity="error",
                    summary="Video frames are converted before checking whether read() succeeded.",
                    path=display_path,
                    line=cvt_line,
                    evidence=lines[cvt_line - 1].strip(),
                    recommendation="Check ret before using frame; break or continue when frame is empty.",
                )
            )
    return issues


def first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


def find_line(lines: list[str], needle: str) -> int | None:
    for idx, line in enumerate(lines, 1):
        if needle in line:
            return idx
    return None
