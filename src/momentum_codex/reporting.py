"""Deal reporting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable


@dataclass
class WeeklyDealSummary:
    """Aggregated view of deal activity for a time window."""

    generated_at: datetime
    total_deals: int
    by_stage: Dict[str, int]
    total_amount: float

    def to_markdown(self) -> str:
        stage_rows = "\n".join(f"- **{stage}**: {count}" for stage, count in sorted(self.by_stage.items()))
        return (
            f"Weekly Deal Summary (generated {self.generated_at:%Y-%m-%d %H:%M UTC})\n"
            f"Total Deals: {self.total_deals}\n"
            f"Total Amount: ${self.total_amount:,.2f}\n"
            f"Breakdown:\n{stage_rows if stage_rows else '- None'}"
        )


def summarize_deals(deals: Iterable[Dict[str, Any]], *, generated_at: datetime) -> WeeklyDealSummary:
    total = 0
    total_amount = 0.0
    stage_counts: Dict[str, int] = {}
    for deal in deals:
        total += 1
        stage = deal.get("properties", {}).get("dealstage", "unknown")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        amount_raw = deal.get("properties", {}).get("amount")
        try:
            total_amount += float(amount_raw) if amount_raw is not None else 0.0
        except (TypeError, ValueError):
            continue
    return WeeklyDealSummary(
        generated_at=generated_at,
        total_deals=total,
        by_stage=stage_counts,
        total_amount=total_amount,
    )
