"""Abstract base class for stock exploration agents.

fin-advisor의 base_agent.py 패턴을 그대로 계승.
StrategyAgent → StockAgent로 도메인 변경.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.agents.models import AgentOpinion, Rebuttal, StockAnalysisContext


class StockAgent(ABC):
    """주식 탐험 전문가 에이전트 기반 클래스.

    각 에이전트는 고유한 관점에서 종목을 평가하고
    AgentOpinion(signal, confidence, rationale)을 반환한다.
    """

    name: str = "base"
    description: str = ""

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

    def _safe_ratio(self, numerator, denominator, default=None):
        """0 나누기 방어 유틸."""
        try:
            if denominator and denominator != 0:
                return numerator / denominator
        except (TypeError, ZeroDivisionError):
            pass
        return default
