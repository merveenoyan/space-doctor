from __future__ import annotations

import difflib
import re
from pathlib import Path


def build_suggested_patch(space_dir: Path) -> str:
    app = space_dir / "app.py"
    if not app.exists():
        return ""
    original = app.read_text(encoding="utf-8", errors="ignore")
    fixed = apply_known_fixes_to_text(original)
    if fixed == original:
        return ""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile="a/app.py",
            tofile="b/app.py",
        )
    )


def apply_known_fixes(space_dir: Path) -> list[Path]:
    app = space_dir / "app.py"
    if not app.exists():
        return []
    original = app.read_text(encoding="utf-8", errors="ignore")
    fixed = apply_known_fixes_to_text(original)
    if fixed == original:
        return []
    app.write_text(fixed, encoding="utf-8")
    return [app]


def apply_known_fixes_to_text(text: str) -> str:
    fixed = text
    fixed = fixed.replace("TextIteratorStreamer(processor,", "TextIteratorStreamer(processor.tokenizer,")
    fixed = re.sub(r"(?m)^(\s*)gr\.Error\(", r"\1raise gr.Error(", fixed)
    fixed = insert_image_initializer(fixed)
    fixed = replace_sample_frames(fixed)
    return fixed


def insert_image_initializer(text: str) -> str:
    if "image = None" in text or "if image is None" not in text:
        return text
    pattern = re.compile(r"(?m)^(\s*)def\s+bot_streaming\([^)]*\):\s*$")
    match = pattern.search(text)
    if not match:
        return text
    indent = match.group(1) + "    "
    insert_at = match.end()
    return text[:insert_at] + f"\n{indent}image = None" + text[insert_at:]


def replace_sample_frames(text: str) -> str:
    match = re.search(r"(?ms)^def sample_frames\(video_file, num_frames\) :\n.*?(?=^@|^def |\Z)", text)
    if not match:
        return text
    replacement = """def sample_frames(video_file, num_frames):
    video = cv2.VideoCapture(video_file)
    total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        video.release()
        return []

    target_frames = max(1, int(num_frames))
    interval = max(1, total_frames // target_frames)
    frames = []
    for i in range(total_frames):
        ret, frame = video.read()
        if not ret:
            break
        if i % interval == 0:
            frames.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        if len(frames) >= target_frames:
            break
    video.release()
    return frames

"""
    return text[: match.start()] + replacement + text[match.end() :]
