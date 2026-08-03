from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.enrichment import load_enrichment  # noqa: E402


class EnrichmentTests(unittest.TestCase):
    def test_missing_or_invalid_file_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual(load_enrichment(root, "2026-08-03"), {})
            target = root / "data" / "processed" / "enrichment" / "2026-08-03" / "technical_chip_summary.json"
            target.parent.mkdir(parents=True)
            target.write_text("not json", encoding="utf-8")
            self.assertEqual(load_enrichment(root, "2026-08-03"), {})

    def test_loads_presentation_fields_without_model_fields(self) -> None:
        payload = {
            "as_of": "2026-08-03",
            "stocks": {
                "2330": {
                    "technical": {"status": "中性", "summary": "日週線摘要"},
                    "chip": "待觀察",
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "data" / "processed" / "enrichment" / "2026-08-03" / "technical_chip_summary.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            loaded = load_enrichment(root, "2026-08-03")
        self.assertEqual(loaded["2330"]["technical"], "中性｜日週線摘要")
        self.assertEqual(loaded["2330"]["chip"], "待觀察")
        self.assertEqual(set(loaded["2330"]), {"technical", "chip", "source_date"})


if __name__ == "__main__":
    unittest.main()
