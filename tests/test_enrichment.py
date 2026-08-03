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
        # 入口頁需要短狀態與長敘述分開；扁平字串保留給 Excel 與各模型單頁。
        self.assertEqual(loaded["2330"]["technical_status"], "中性")
        self.assertEqual(loaded["2330"]["technical_summary"], "日週線摘要")
        self.assertEqual(loaded["2330"]["chip_status"], "待觀察")
        self.assertEqual(loaded["2330"]["chip_summary"], "")
        # 好壞由產生資料的一端決定，未指定時一律中性，報表不從字面猜測。
        self.assertEqual(loaded["2330"]["technical_tone"], "mid")
        self.assertEqual(loaded["2330"]["chip_tone"], "mid")
        self.assertEqual(
            set(loaded["2330"]),
            {
                "technical", "chip", "source_date",
                "technical_status", "technical_summary", "technical_tone",
                "chip_status", "chip_summary", "chip_tone",
            },
        )

    def test_tone_is_taken_from_producer_and_validated(self) -> None:
        payload = {
            "as_of": "2026-08-03",
            "stocks": {
                "1101": {
                    "technical": {"status": "順勢", "summary": "站上均線", "tone": "up"},
                    "chip": {"status": "散戶增加", "summary": "融資走高", "tone": "不是有效值"},
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "data" / "processed" / "enrichment" / "2026-08-03" / "technical_chip_summary.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            loaded = load_enrichment(root, "2026-08-03")
        self.assertEqual(loaded["1101"]["technical_tone"], "up")
        self.assertEqual(loaded["1101"]["chip_tone"], "mid")


if __name__ == "__main__":
    unittest.main()
