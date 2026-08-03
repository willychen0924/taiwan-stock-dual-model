from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import clamp, descending_score, linear_score


SUMMARY_MIN_CHARS = 50
SUMMARY_MAX_CHARS = 70


def load_momentum_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    weights = config["weights"]
    if sum(float(value) for value in weights.values()) != 100:
        raise ValueError("營運動能模型權重合計必須為100")
    for section, expected in weights.items():
        actual = sum(float(value) for value in config["components"][section].values())
        if actual != float(expected):
            raise ValueError(f"{section} 細項分數合計必須為 {expected}")
    return config


def _compact_percent(value: Any) -> str:
    magnitude = abs(float(value))
    if magnitude >= 10:
        return "逾999%"
    return f"{magnitude:.0%}"


def _percentage_points(value: Any) -> str:
    magnitude = abs(float(value)) * 100
    return f"{magnitude:.1f}個百分點"


def _qualitative_clause(row: dict[str, Any]) -> str:
    status = row.get("governance_status") or "待複核"
    if row.get("manual_exclude") or status == "否決":
        return "治理覆核列為人工排除"
    if status == "通過" and row.get("catalyst"):
        return "治理與成長來源已人工覆核"
    return "治理與成長來源仍待查證"


def _momentum_risk(row: dict[str, Any], min_turnover: float) -> str:
    acceleration = row.get("revenue_acceleration")
    margin_change = row.get("ttm_operating_margin_change")
    cash_conversion = row.get("cash_conversion")
    latest_revenue = row.get("latest_revenue_yoy")
    revenue_3m = row.get("revenue_3m_yoy")
    per = row.get("per")
    turnover = row.get("avg_daily_turnover")

    if acceleration is not None and float(acceleration) < 0:
        return f"營收成長減速{_percentage_points(acceleration)}"
    if margin_change is not None and float(margin_change) < 0:
        return f"營益率年減{_percentage_points(margin_change)}"
    if cash_conversion is not None and float(cash_conversion) < 0.5:
        return "現金轉換偏弱"
    if (
        latest_revenue is not None
        and revenue_3m is not None
        and float(latest_revenue) + 0.05 < float(revenue_3m)
    ):
        return "最新月增速低於近三月"
    if per is not None and float(per) >= 30:
        return f"本益比{float(per):.1f}倍偏高"
    if turnover is not None and float(turnover) < min_turnover * 1.5:
        return "成交額接近流動性門檻"
    return "動能延續性仍需追蹤"


def _momentum_details(row: dict[str, Any]) -> list[str]:
    details: list[str] = []
    revenue_3m = row.get("revenue_3m_yoy")
    acceleration = row.get("revenue_acceleration")
    net_income_growth = row.get("ttm_net_income_growth")
    margin_change = row.get("ttm_operating_margin_change")
    cash_conversion = row.get("cash_conversion")
    score = row.get("operating_momentum_score")

    if revenue_3m is not None:
        direction = "年增" if float(revenue_3m) >= 0 else "年減"
        details.append(f"近三月營收{direction}{_compact_percent(revenue_3m)}")
    if acceleration is not None and float(acceleration) >= 0:
        details.append(f"營收動能加速{_percentage_points(acceleration)}")
    if net_income_growth is not None:
        direction = "年增" if float(net_income_growth) >= 0 else "年減"
        details.append(f"TTM淨利{direction}{_compact_percent(net_income_growth)}")
    if margin_change is not None and float(margin_change) >= 0:
        details.append(f"營益率年增{_percentage_points(margin_change)}")
    if cash_conversion is not None:
        details.append(f"現金轉換{float(cash_conversion):.1f}倍")
    if score is not None:
        details.append(f"營運動能分{float(score):.1f}分")
    return details or ["可用動能欄位有限"]


def build_momentum_summary(row: dict[str, Any], min_turnover: float = 20_000_000) -> str:
    name = str(row.get("stock_name") or row.get("stock_id") or "公司")
    passed = bool(row.get("hard_pass"))
    qualitative = _qualitative_clause(row)
    if passed:
        prefix = f"{name}通過動能門檻，"
        risk = _momentum_risk(row, min_turnover)

        def compose(details: list[str]) -> str:
            return f"{prefix}{'、'.join(details)}；惟{risk}，{qualitative}。"

        candidates = _momentum_details(row)
    else:
        prefix = f"{name}未通過動能門檻，"
        reasons = [item for item in str(row.get("exclusion_reasons") or "").split("；") if item]
        aliases = {
            "20日均成交金額不足": "成交金額不足",
            "負債比率超標或缺漏": "負債比率未達標",
            "前期TTM淨利非正，列轉機觀察": "前期淨利非正，列轉機觀察",
        }
        candidates = [f"主要原因為{aliases.get(reason, reason)}" for reason in reasons]
        candidates.append(f"動能總分{float(row.get('total_score') or 0):.1f}分")

        def compose(details: list[str]) -> str:
            return f"{prefix}{'、'.join(details)}；{qualitative}。"

    selected: list[str] = []
    for clause in candidates:
        candidate = compose([*selected, clause])
        if len(candidate) <= SUMMARY_MAX_CHARS:
            selected.append(clause)
        if len(selected) >= 3 and len(compose(selected)) >= SUMMARY_MIN_CHARS:
            break

    summary = compose(selected or [candidates[0]])
    if len(summary) < SUMMARY_MIN_CHARS:
        filler = "後續仍需搭配基本面與公開資訊持續判讀"
        candidate = summary[:-1] + f"，{filler}。"
        if len(candidate) <= SUMMARY_MAX_CHARS:
            summary = candidate
    if len(summary) > SUMMARY_MAX_CHARS:
        summary = summary[: SUMMARY_MAX_CHARS - 1].rstrip("，、；") + "。"
    return summary


def build_momentum_result(base_result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    targets = config["score_targets"]
    points = config["components"]
    gates = config["hard_gates"]
    financial_industries = set(base_result["config"]["universe"]["financial_industries"])
    rows: list[dict[str, Any]] = []

    for source in base_result["results"]:
        row = dict(source)
        row["value_rank"] = source.get("rank")
        row["value_hard_pass"] = source.get("hard_pass")
        row["value_total_score"] = source.get("total_score")

        momentum_score = (
            linear_score(
                row.get("revenue_3m_yoy"),
                float(targets["revenue_growth_floor"]),
                float(targets["revenue_growth_target"]),
                float(points["operating_momentum"]["revenue_3m_yoy"]),
            )
            + linear_score(
                row.get("latest_revenue_yoy"),
                float(targets["revenue_growth_floor"]),
                float(targets["revenue_growth_target"]),
                float(points["operating_momentum"]["latest_revenue_yoy"]),
            )
            + linear_score(
                row.get("revenue_acceleration"),
                float(targets["revenue_acceleration_floor"]),
                float(targets["revenue_acceleration_target"]),
                float(points["operating_momentum"]["revenue_acceleration"]),
            )
            + linear_score(
                row.get("ttm_net_income_growth"),
                float(targets["net_income_growth_floor"]),
                float(targets["net_income_growth_target"]),
                float(points["operating_momentum"]["ttm_net_income_growth"]),
            )
            + (
                float(points["operating_momentum"]["sector_margin_percentile"])
                * float(row["sector_margin_percentile"])
                if row.get("sector_margin_percentile") is not None
                else 0
            )
            + linear_score(
                row.get("ttm_operating_margin_change"),
                float(targets["margin_change_floor"]),
                float(targets["margin_change_target"]),
                float(points["operating_momentum"]["operating_margin_change"]),
            )
        )
        quality_score = (
            float(points["quality"]["profitable_years"]) * clamp(float(row.get("profitable_years") or 0) / 5)
            + float(points["quality"]["positive_fcf_years"])
            * clamp(float(row.get("positive_fcf_years") or 0) / 5)
            + linear_score(
                row.get("cash_conversion"),
                float(targets["cash_conversion_floor"]),
                float(targets["cash_conversion_target"]),
                float(points["quality"]["cash_conversion"]),
            )
            + descending_score(
                row.get("liabilities_ratio"),
                float(targets["liabilities_ratio_best"]),
                float(targets["liabilities_ratio_worst"]),
                float(points["quality"]["liabilities_ratio"]),
            )
            + linear_score(
                row.get("net_cash_ratio"),
                float(targets["net_cash_ratio_floor"]),
                float(targets["net_cash_ratio_target"]),
                float(points["quality"]["net_cash_ratio"]),
            )
        )
        valuation_liquidity_score = (
            float(points["valuation_liquidity"]["sector_per_percentile"])
            * (1 - float(row["sector_per_percentile"]))
            if row.get("sector_per_percentile") is not None
            else 0
        ) + (
            float(points["valuation_liquidity"]["sector_pbr_percentile"])
            * (1 - float(row["sector_pbr_percentile"]))
            if row.get("sector_pbr_percentile") is not None
            else 0
        )
        valuation_liquidity_score += descending_score(
            row.get("per"),
            float(targets["per_best"]),
            float(targets["per_worst"]),
            float(points["valuation_liquidity"]["absolute_per"]),
        )
        valuation_liquidity_score += linear_score(
            row.get("avg_daily_turnover"),
            float(gates["min_avg_daily_turnover_twd"]),
            float(targets["turnover_target_twd"]),
            float(points["valuation_liquidity"]["turnover"]),
        )

        row["operating_momentum_score"] = round(momentum_score, 4)
        row["quality_score"] = round(quality_score, 4)
        row["valuation_liquidity_score"] = round(valuation_liquidity_score, 4)
        row["total_score"] = round(momentum_score + quality_score + valuation_liquidity_score, 4)

        reasons: list[str] = []
        if row["industry"] in financial_industries:
            reasons.append("金融業需使用專用模型")
        if row.get("manual_exclude"):
            reasons.append("人工排除")
        if row.get("market_value") is None or row.get("close") is None:
            reasons.append("缺少市值或收盤價")
        if row.get("complete_profit_years", 0) < int(gates["min_complete_profit_years"]):
            reasons.append("至少三年獲利資料不完整")
        if gates.get("require_positive_ttm_income") and float(row.get("ttm_net_income") or 0) <= 0:
            reasons.append("TTM淨利非正或缺漏")
        if gates.get("require_positive_prior_ttm_income") and float(row.get("prior_ttm_net_income") or 0) <= 0:
            reasons.append("前期TTM淨利非正，列轉機觀察")
        if gates.get("require_revenue_acceleration_data") and row.get("revenue_acceleration") is None:
            reasons.append("近六個月營收加速度資料不完整")
        if row.get("liabilities_ratio") is None or float(row["liabilities_ratio"]) > float(
            gates["max_liabilities_to_assets"]
        ):
            reasons.append("負債比率超標或缺漏")
        if row.get("avg_daily_turnover") is None or float(row["avg_daily_turnover"]) < float(
            gates["min_avg_daily_turnover_twd"]
        ):
            reasons.append("20日均成交金額不足")

        row["hard_pass"] = not reasons
        row["exclusion_reasons"] = "；".join(reasons)
        row["momentum_bucket"] = (
            "轉機觀察"
            if float(row.get("ttm_net_income") or 0) > 0 and float(row.get("prior_ttm_net_income") or 0) <= 0
            else "一般成長"
        )
        missing = []
        for label, key in (
            ("3M營收", "revenue_3m_yoy"),
            ("營收加速度", "revenue_acceleration"),
            ("TTM淨利成長", "ttm_net_income_growth"),
            ("營益率變化", "ttm_operating_margin_change"),
            ("現金轉換", "cash_conversion"),
        ):
            if row.get(key) is None:
                missing.append(label)
        row["missing_flags"] = "、".join(missing)
        rows.append(row)

    rows.sort(key=lambda item: (not item["hard_pass"], -item["total_score"], item["stock_id"]))
    watchlist_size = int(config["report"]["watchlist_size"])
    focus_size = int(config["report"]["focus_size"])
    rank = 0
    for row in rows:
        if row["hard_pass"]:
            rank += 1
            row["rank"] = rank
            row["funnel_stage"] = (
                "精華20" if rank <= focus_size else "自選100" if rank <= watchlist_size else "動能通過"
            )
        else:
            row["rank"] = None
            row["funnel_stage"] = "轉機觀察" if row["momentum_bucket"] == "轉機觀察" else "基礎觀察"

    active_rows = [row for row in rows if row.get("close") is not None and row["industry"] not in financial_industries]
    hard_pass_count = sum(row["hard_pass"] for row in rows)
    turnaround_count = sum(row["momentum_bucket"] == "轉機觀察" for row in rows)

    def coverage(key: str) -> float:
        return sum(row.get(key) is not None for row in active_rows) / max(1, len(active_rows))

    acceleration_coverage = coverage("revenue_acceleration")
    margin_change_coverage = coverage("ttm_operating_margin_change")
    cash_conversion_coverage = coverage("cash_conversion")
    weight_total = sum(float(value) for value in config["weights"].values())
    checks = [
        {
            "check": "評分權重合計",
            "actual": weight_total,
            "expected": 100,
            "tolerance": 0,
            "status": "OK" if weight_total == 100 else "FAIL",
            "notes": "營運動能60／動能品質25／估值流動性15",
        },
        {
            "check": "營收加速度覆蓋率",
            "actual": acceleration_coverage,
            "expected": 0.80,
            "tolerance": 0,
            "status": "OK" if acceleration_coverage >= 0.80 else "WARN",
            "notes": "需最近六個月及去年同期月營收完整",
        },
        {
            "check": "營益率年變化覆蓋率",
            "actual": margin_change_coverage,
            "expected": 0.70,
            "tolerance": 0,
            "status": "OK" if margin_change_coverage >= 0.70 else "WARN",
            "notes": "比較目前TTM與前期TTM營益率",
        },
        {
            "check": "現金轉換覆蓋率",
            "actual": cash_conversion_coverage,
            "expected": 0.65,
            "tolerance": 0,
            "status": "OK" if cash_conversion_coverage >= 0.65 else "WARN",
            "notes": "最近完整年度營業現金流／淨利",
        },
        {
            "check": "量化硬門檻通過數",
            "actual": hard_pass_count,
            "expected": 1,
            "tolerance": 0,
            "status": "OK" if hard_pass_count >= 1 else "WARN",
            "notes": "0檔代表目前沒有符合完整條件的公司",
        },
        {
            "check": "共用資料模型狀態",
            "actual": base_result["metadata"]["model_status"],
            "expected": "OK",
            "tolerance": 0,
            "status": "FAIL" if base_result["metadata"]["model_status"] == "FAIL" else "OK",
            "notes": "沿用防禦型價值報表的市場與財報資料層",
        },
    ]
    if any(item["status"] == "FAIL" for item in checks):
        model_status = "FAIL"
    elif any(item["status"] == "WARN" for item in checks):
        model_status = "WARN"
    else:
        model_status = "OK"

    min_turnover = float(gates["min_avg_daily_turnover_twd"])
    for row in rows:
        row["model_summary"] = build_momentum_summary(row, min_turnover)

    metadata = dict(base_result["metadata"])
    metadata.update(
        {
            "model_id": config["model"]["id"],
            "model_name": config["model"]["name"],
            "hard_pass_count": hard_pass_count,
            "watchlist_count": min(hard_pass_count, watchlist_size),
            "focus_count": min(hard_pass_count, focus_size),
            "turnaround_count": turnaround_count,
            "model_status": model_status,
            "revenue_acceleration_coverage": acceleration_coverage,
            "margin_change_coverage": margin_change_coverage,
            "cash_conversion_coverage": cash_conversion_coverage,
        }
    )
    return {"metadata": metadata, "config": config, "checks": checks, "results": rows}
