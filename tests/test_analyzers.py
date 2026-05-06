from __future__ import annotations

import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from space_doctor.analyzers import analyze_space
from space_doctor.patches import apply_known_fixes_to_text

SAMPLE = ROOT / "examples" / "broken-llava-space"


class AnalyzerTests(unittest.TestCase):
    def test_detects_sample_failures(self) -> None:
        issues = analyze_space(SAMPLE)
        rule_ids = {issue.rule_id for issue in issues}
        self.assertIn("module-level-gpu-load", rule_ids)
        self.assertIn("streamer-uses-processor", rule_ids)
        self.assertIn("frame-sampling-zero-division", rule_ids)
        self.assertIn("ret-checked-after-frame-use", rule_ids)
        self.assertIn("possibly-uninitialized-image", rule_ids)
        self.assertIn("gr-error-not-raised", rule_ids)

    def test_known_fixes_rewrite_common_patterns(self) -> None:
        original = (SAMPLE / "app.py").read_text(encoding="utf-8")
        fixed = apply_known_fixes_to_text(original)
        self.assertIn("image = None", fixed)
        self.assertIn("TextIteratorStreamer(processor.tokenizer,", fixed)
        self.assertIn("raise gr.Error(", fixed)
        self.assertIn("interval = max(1, total_frames // target_frames)", fixed)
        self.assertNotIn("interval = total_frames // num_frames", fixed)


if __name__ == "__main__":
    unittest.main()
