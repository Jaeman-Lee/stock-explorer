"""Data validation layer to prevent hallucination in agent evaluations.

Validates fundamentals from yfinance, checks bounds, tracks data completeness.
Shared logic with fin-advisor/src/debate/data_validator.py.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# Reasonable bounds for financial metrics.
METRIC_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "forwardPE": (-500, 2000),
    "trailingPE": (-500, 2000),
    "priceToBook": (-100, 500),
    "profitMargins": (-10, 1.0),
    "grossMargins": (-5, 1.0),
    "operatingMargins": (-10, 1.0),
    "revenueGrowth": (-1.0, 50.0),
    "earningsGrowth": (-10.0, 100.0),
    "dividendYield": (0, 1.0),
    "payoutRatio": (-5, 10.0),
    "debtToEquity": (-500, 5000),
    "freeCashflow": (-1e12, 1e12),
    "marketCap": (0, 20e12),
    "returnOnEquity": (-10, 10),
    "returnOnAssets": (-5, 5),
    "pegRatio": (-100, 500),
    "enterpriseToEbitda": (-500, 2000),
}

MIN_FUNDAMENTALS_COUNT = 3


@dataclass
class DataQuality:
    """Tracks data completeness and reliability."""

    completeness: float = 0.0
    available_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suspect_fields: list[str] = field(default_factory=list)
    data_age_days: int | None = None

    @property
    def is_sufficient(self) -> bool:
        return len(self.available_fields) >= MIN_FUNDAMENTALS_COUNT

    @property
    def confidence_penalty(self) -> float:
        """Multiplier (0.3-1.0) to apply to agent confidence."""
        if not self.is_sufficient:
            return 0.3
        penalty = 1.0
        penalty -= (1.0 - self.completeness) * 0.3
        penalty -= min(len(self.suspect_fields) * 0.05, 0.2)
        if self.data_age_days is not None and self.data_age_days > 3:
            penalty -= min(self.data_age_days * 0.02, 0.15)
        return max(0.3, penalty)


def validate_fundamentals(raw: dict) -> tuple[dict, list[str]]:
    """Validate and sanitize fundamentals. Remove out-of-bounds values."""
    if not raw:
        return {}, ["펀더멘탈 데이터 없음"]

    cleaned = dict(raw)
    warnings = []

    for key, value in raw.items():
        if value is None or not isinstance(value, (int, float)):
            continue
        # NaN/Inf 제거
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            cleaned[key] = None
            continue
        bounds = METRIC_BOUNDS.get(key)
        if bounds is None:
            continue
        lo, hi = bounds
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            warnings.append(f"{key}={value} 이상값 — 제외됨.")
            cleaned[key] = None

    return cleaned, warnings


def assess_data_quality(
    fundamentals: dict,
    market_data: list[dict],
) -> DataQuality:
    """Assess overall data quality for context."""
    dq = DataQuality()

    expected = [
        "trailingPE", "forwardPE", "priceToBook", "marketCap",
        "freeCashflow", "profitMargins", "grossMargins",
        "revenueGrowth", "earningsGrowth", "debtToEquity",
        "returnOnEquity",
    ]
    for key in expected:
        if fundamentals.get(key) is not None:
            dq.available_fields.append(key)
        else:
            dq.missing_fields.append(key)

    dq.completeness = len(dq.available_fields) / len(expected) if expected else 0.0

    # Market data freshness
    if market_data:
        latest_date_str = market_data[-1].get("date", "")
        if latest_date_str:
            try:
                latest_date = datetime.strptime(latest_date_str[:10], "%Y-%m-%d")
                age = (datetime.now() - latest_date).days
                dq.data_age_days = age
                if age > 7:
                    dq.warnings.append(f"시장 데이터가 {age}일 전입니다.")
            except (ValueError, TypeError):
                pass
    else:
        dq.warnings.append("시장 데이터(OHLCV) 없음.")

    if not dq.is_sufficient:
        dq.warnings.append(
            f"펀더멘탈 지표 {len(dq.available_fields)}개 — 최소 {MIN_FUNDAMENTALS_COUNT}개 필요."
        )

    return dq
