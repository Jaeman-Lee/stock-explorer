"""성장성 평가 에이전트.

평가 기준: 매출 성장 추이, EPS 성장, 시장 확장 가능성, 미래 가이던스.
fin-advisor의 growth_investor 관점을 계승 + 확장.
"""

from __future__ import annotations

from src.agents.base_agent import StockAgent
from src.agents.models import AgentOpinion, Signal, StockAnalysisContext


class GrowthAgent(StockAgent):
    """성장성 및 미래 가치 창출 능력 평가 에이전트."""

    name = "growth-analyst"
    description = "매출/이익 성장 추이, TAM 확장성, 미래 성장 동력 평가"

    def evaluate(self, context: StockAnalysisContext) -> AgentOpinion:
        f = context.fundamentals
        history = context.financial_history  # [{year, revenue, net_income, eps}, ...]

        score = 0
        max_score = 0
        metrics: dict = {}
        strengths: list[str] = []
        risk_flags: list[str] = []

        # ── 최근 매출 성장률 YoY (25점) ─────────────────────────────────────
        rev_growth = f.get("revenueGrowth")
        if rev_growth is not None:
            max_score += 25
            metrics["revenue_growth_yoy_pct"] = round(rev_growth * 100, 1)
            if rev_growth >= 0.30:
                score += 25
                strengths.append(f"하이퍼 성장 매출 +{rev_growth*100:.0f}% YoY")
            elif rev_growth >= 0.20:
                score += 20
                strengths.append(f"고성장 매출 +{rev_growth*100:.0f}% YoY")
            elif rev_growth >= 0.10:
                score += 14
            elif rev_growth >= 0.05:
                score += 8
            elif rev_growth >= 0.0:
                score += 4
            else:
                risk_flags.append(f"매출 역성장 {rev_growth*100:.1f}%")

        # ── EPS 성장률 YoY (20점) ────────────────────────────────────────────
        eps_growth = f.get("earningsGrowth")
        if eps_growth is not None:
            max_score += 20
            metrics["eps_growth_yoy_pct"] = round(eps_growth * 100, 1)
            if eps_growth >= 0.25:
                score += 20
                strengths.append(f"EPS 고성장 +{eps_growth*100:.0f}% YoY")
            elif eps_growth >= 0.15:
                score += 14
            elif eps_growth >= 0.05:
                score += 9
            elif eps_growth >= 0.0:
                score += 4
            else:
                risk_flags.append(f"EPS 역성장 {eps_growth*100:.1f}%")

        # ── 3년 매출 CAGR 추이 (20점) ──────────────────────────────────────
        cagr = self._compute_revenue_cagr(history, years=3)
        if cagr is not None:
            max_score += 20
            metrics["revenue_cagr_3y_pct"] = round(cagr * 100, 1)
            if cagr >= 0.20:
                score += 20
                strengths.append(f"3년 매출 CAGR {cagr*100:.0f}% — 지속적 고성장")
            elif cagr >= 0.12:
                score += 14
            elif cagr >= 0.07:
                score += 9
            elif cagr >= 0.02:
                score += 5
            else:
                risk_flags.append(f"낮은 3년 CAGR {cagr*100:.1f}%")

        # ── 애널리스트 성장 전망 (15점) ─────────────────────────────────────
        target_price = f.get("targetMeanPrice")
        current_price = f.get("currentPrice") or f.get("regularMarketPrice")
        analyst_count = f.get("numberOfAnalystOpinions") or 0

        if target_price and current_price and analyst_count >= 3:
            upside = (target_price - current_price) / current_price
            max_score += 15
            metrics["analyst_upside_pct"] = round(upside * 100, 1)
            metrics["analyst_count"] = analyst_count
            if upside >= 0.30:
                score += 15
                strengths.append(f"애널리스트 컨센서스 상승 여력 {upside*100:.0f}%")
            elif upside >= 0.15:
                score += 11
            elif upside >= 0.05:
                score += 7
            elif upside >= -0.05:
                score += 4
            else:
                risk_flags.append(f"애널리스트 하락 전망 {upside*100:.1f}%")

        # ── 매출 성장 가속/감속 추이 (10점) ─────────────────────────────────
        trend = self._growth_trend(history)
        if trend is not None:
            max_score += 10
            metrics["growth_trend"] = trend
            if trend == "accelerating":
                score += 10
                strengths.append("성장 가속 추이 확인")
            elif trend == "stable":
                score += 6
            elif trend == "decelerating":
                score += 3
                risk_flags.append("성장 둔화 추이")
            else:
                score += 1
                risk_flags.append("성장률 변동 불안정")

        # ── R&D 투자 수준 (10점) ─────────────────────────────────────────────
        rd_pct = self._rd_to_revenue(f)
        if rd_pct is not None:
            max_score += 10
            metrics["rd_to_revenue_pct"] = round(rd_pct * 100, 1)
            if rd_pct >= 0.15:
                score += 10
                strengths.append(f"R&D 집약 투자 매출 대비 {rd_pct*100:.0f}%")
            elif rd_pct >= 0.08:
                score += 7
            elif rd_pct >= 0.03:
                score += 4
            elif rd_pct == 0.0:
                pass  # 제조업 등 R&D 불필요 업종 중립
            else:
                score += 2

        # ── 종합 판정 ───────────────────────────────────────────────────────
        if max_score == 0:
            return AgentOpinion(
                agent_name=self.name,
                signal=Signal.WATCH,
                confidence=0.2,
                rationale="성장성 데이터 불충분",
                key_metrics=metrics,
                risk_flags=["성장성 데이터 없음"],
            )

        pct = score / max_score
        metrics["growth_score"] = f"{score}/{max_score} ({pct*100:.0f}%)"

        if pct >= 0.75:
            signal = Signal.STRONG_BUY
            confidence = min(0.82 + (pct - 0.75) * 0.5, 0.95)
            rationale = (
                f"강한 성장 모멘텀 ({pct*100:.0f}%). "
                f"{', '.join(strengths[:2]) if strengths else '복수 지표에서 고성장 확인'}."
            )
        elif pct >= 0.55:
            signal = Signal.BUY
            confidence = 0.60 + (pct - 0.55) * 1.1
            rationale = (
                f"견조한 성장세 ({pct*100:.0f}%). "
                f"{strengths[0] if strengths else '성장성 양호'}."
            )
        elif pct >= 0.35:
            signal = Signal.WATCH
            confidence = 0.50
            rationale = f"성장 둔화 또는 불확실 ({pct*100:.0f}%). 추이 모니터링 필요."
        elif pct >= 0.15:
            signal = Signal.PASS
            confidence = 0.60
            rationale = (
                f"성장성 미흡 ({pct*100:.0f}%). "
                f"{risk_flags[0] if risk_flags else '성장 동력 약화'}."
            )
        else:
            signal = Signal.AVOID
            confidence = 0.70
            rationale = (
                f"성장 정체 또는 후퇴 ({pct*100:.0f}%). "
                f"{'; '.join(risk_flags[:2]) if risk_flags else '성장 투자 부적합'}."
            )

        return AgentOpinion(
            agent_name=self.name,
            signal=signal,
            confidence=round(confidence, 2),
            rationale=rationale,
            key_metrics=metrics,
            risk_flags=risk_flags,
            strengths=strengths,
        )

    def _compute_revenue_cagr(
        self, history: list[dict], years: int = 3
    ) -> float | None:
        """연간 재무 이력에서 매출 CAGR을 계산한다."""
        revenues = [h.get("revenue") for h in history if h.get("revenue") and h["revenue"] > 0]
        if len(revenues) < 2:
            return None
        n = min(years, len(revenues) - 1)
        start, end = revenues[-(n + 1)], revenues[-1]
        try:
            return (end / start) ** (1 / n) - 1
        except (ZeroDivisionError, ValueError):
            return None

    def _growth_trend(self, history: list[dict]) -> str | None:
        """최근 3개년 매출 성장률 추이를 분류한다."""
        revenues = [h.get("revenue") for h in history if h.get("revenue") and h["revenue"] > 0]
        if len(revenues) < 3:
            return None
        rates = [(revenues[i] / revenues[i - 1]) - 1 for i in range(1, len(revenues))]
        if len(rates) < 2:
            return None
        recent, older = rates[-1], rates[-2]
        diff = recent - older
        if diff >= 0.05:
            return "accelerating"
        elif diff >= -0.03:
            return "stable"
        elif diff >= -0.10:
            return "decelerating"
        else:
            return "sharp_decline"

    def _rd_to_revenue(self, f: dict) -> float | None:
        """R&D 비용 / 매출 비율."""
        rd = f.get("researchAndDevelopment")
        rev = f.get("totalRevenue")
        return self._safe_ratio(rd, rev)
