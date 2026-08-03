from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_TONES = {"up", "mid", "down"}


def _display_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip() or "—"
    if not isinstance(value, dict):
        return "—"
    status = str(value.get("status") or "").strip()
    summary = str(value.get("summary") or value.get("note") or "").strip()
    if status and summary and status != summary:
        return f"{status}｜{summary}"
    return status or summary or "—"


def _parts(value: Any) -> tuple[str, str, str]:
    """Split an enrichment block into (status, summary, tone) for presentation.

    Tone is supplied by the producer; the report never infers whether a state is
    good or bad from its wording.
    """
    if isinstance(value, str):
        return value.strip(), "", "mid"
    if not isinstance(value, dict):
        return "", "", "mid"
    status = str(value.get("status") or "").strip()
    summary = str(value.get("summary") or value.get("note") or "").strip()
    tone = str(value.get("tone") or "mid").strip()
    return status, summary, tone if tone in _TONES else "mid"


def load_enrichment(root: Path, as_of: str) -> dict[str, dict[str, str]]:
    """Load optional presentation-only technical/chip summaries without affecting model state."""
    source = root / "data" / "processed" / "enrichment" / as_of / "technical_chip_summary.json"
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    stocks = payload.get("stocks", {})
    if not isinstance(stocks, dict):
        return {}
    default_source_date = str(payload.get("as_of") or as_of)
    output: dict[str, dict[str, str]] = {}
    for stock_id, item in stocks.items():
        if not isinstance(item, dict):
            continue
        technical_status, technical_summary, technical_tone = _parts(item.get("technical"))
        chip_status, chip_summary, chip_tone = _parts(item.get("chip"))
        output[str(stock_id)] = {
            # Flattened strings keep the Excel builders and per-model pages working.
            "technical": _display_value(item.get("technical")),
            "chip": _display_value(item.get("chip")),
            # Split fields let the portal show a short chip plus the full sentence.
            "technical_status": technical_status,
            "technical_summary": technical_summary,
            "technical_tone": technical_tone,
            "chip_status": chip_status,
            "chip_summary": chip_summary,
            "chip_tone": chip_tone,
            "source_date": str(item.get("source_date") or default_source_date),
        }
    return output
