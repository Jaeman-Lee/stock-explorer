"""Abstract base class for stock exploration agents.

fin-advisor의 base_agent.py 패턴을 그대로 계승.
StrategyAgent → StockAgent로 도메인 변경.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod

from src.agents.models import AgentOpinion, Rebuttal, StockAnalysisContext
from src.utils.config import ENABLE_JITTER, JITTER_RANGE, get_sector_thresholds


class StockAgent(ABC):
    """주식 탐험 전문가 에이전트 기반 클래스.

    각 에이전트는 고유한 관점에서 종목을 평가하고
    AgentOpinion(signal, confidence, rationale)을 반환한다.
    """

    name: str = "base"
    description: str = ""
    _needs_fundamentals: bool = True

    @abstractmethod
    def evaluate(self, context: StockAnalysisContext) -> AgentOpinion:
        """주어진 컨텍스트로 종목 평가 의견을 생성한다."""
        ...

    def rebut(
        self, own_opinion: AgentOpinion, opposing: AgentOpinion
    ) -> Rebuttal | None:
        """상충하는 의견에 반박한다.

        fin-advisor의 rebut() 패턴을 그대로 계승.
        신호가 다를 때만 반박 생성.
        """
        if own_opinion.signal == opposing.signal:
            return None

        return Rebuttal(
            agent_name=self.name,
            target_agent=opposing.agent_name,
            argument=(
                f"{self.name}이(가) {opposing.agent_name}에 반박: "
                f"'{opposing.rationale}' — 그러나 {own_opinion.rationale}"
            ),
        )

    def _latest_indicators(self, context: StockAnalysisContext) -> dict:
        """최신 기술적 지표를 추출한다. (fin-advisor 그대로 재사용)"""
        if not context.market_data:
            return {}
        latest = context.market_data[-1]
        return {
            "close": latest.get("close"),
            "rsi_14": latest.get("rsi_14"),
            "macd": latest.get("macd"),
            "macd_signal": latest.get("macd_signal"),
            "macd_hist": latest.get("macd_hist"),
            "sma_20": latest.get("sma_20"),
            "sma_50": latest.get("sma_50"),
            "sma_200": latest.get("sma_200"),
            "bb_upper": latest.get("bb_upper"),
            "bb_lower": latest.get("bb_lower"),
            "bb_mid": latest.get("bb_mid"),
            "volume": latest.get("volume"),
        }

    def _get_thresholds(self, context: StockAnalysisContext) -> dict:
        """컨텍스트의 섹터 정보로 적절한 임계값을 반환한다."""
        sector = context.fundamentals.get("sector")
        return get_sector_thresholds(sector)

    def _jitter(self, value: float) -> float:
        """임계값에 ±JITTER_RANGE 범위의 노이즈를 부여한다.

        토론 다양성 확보를 위해 매 실행마다 미세하게 다른 판단 경계를 생성.
        ENABLE_JITTER=False이면 원래 값을 그대로 반환.
        """
        if not ENABLE_JITTER:
            return value
        noise = random.uniform(-JITTER_RANGE, JITTER_RANGE)
        return value * (1.0 + noise)

    def _safe_ratio(self, numerator, denominator, default=None):
        """0 나누기 방어 유틸."""
        try:
            if denominator and denominator != 0:
                return numerator / denominator
        except (TypeError, ZeroDivisionError):
            pass
        return default

    def _apply_data_quality_penalty(
        self, confidence: float, context: StockAnalysisContext
    ) -> float:
        """데이터 품질에 따라 confidence를 감소시킨다.

        모든 에이전트는 의견 반환 전에 반드시 이 메서드를 호출해야 함.
        """
        dq = context.data_quality
        if not self._needs_fundamentals:
            penalty = 1.0
            if dq.data_age_days is not None and dq.data_age_days > 3:
                penalty -= min(dq.data_age_days * 0.02, 0.15)
            return round(max(0.5, confidence * penalty), 2)

        penalty = dq.confidence_penalty
        adjusted = confidence * penalty
        return round(max(0.05, adjusted), 2)

    def _add_data_warnings(
        self, flags: list[str], context: StockAnalysisContext
    ) -> None:
        """데이터 품질 경고를 리스크 플래그에 추가."""
        if not context.data_quality.is_sufficient:
            flags.append("데이터 부족 — 신뢰도 낮음")
        for w in context.data_quality.warnings[:2]:
            flags.append(f"⚠ {w}")
