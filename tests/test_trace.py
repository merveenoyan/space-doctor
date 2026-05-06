from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from space_doctor.trace import TraceWriter


class TraceTests(unittest.TestCase):
    def test_trace_writer_emits_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            writer = TraceWriter(path, run_id="run-1")
            writer.write("started", target="demo")
            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(row["type"], "space_doctor_event")
            self.assertEqual(row["run_id"], "run-1")
            self.assertEqual(row["event"], "started")
            self.assertEqual(row["payload"]["target"], "demo")


if __name__ == "__main__":
    unittest.main()
