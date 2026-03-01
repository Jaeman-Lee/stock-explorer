"""리스크 평가 에이전트 (거부권 보유).

평가 기준: 재무 리스크, 사업 리스크, 회계 품질, 내부자 동향.
fin-advisor의 risk_manager.py 패턴을 계승.
AVOID 신호 + 높은 신뢰도일 때 거부권 행사.
"""

from __future__ import annotations

from src.agents.base_agent import StockAgent
from src.agents.models import AgentOpinion, Signal, StockAnalysisContext


class RiskAgent(StockAgent):
    """리스크 식별 및 거부권 평가 에이전트.

    fin-advisor risk_manager와 동일하게 AVOID + confidence >= 0.8이면
    Moderator에서 RED_FLAG urgency로 격상.
    """

    name = "risk-analyst"
    description = "재무 리스크·부채·현금소진·회계 품질 점검 (거부권 보유)"

    # 리스크 임계값 (config에서 오버라이드 가능)
    MAX_DEBT_TO_EQUITY = 3.0
    MIN_CURRENT_RATIO = 0.8
    MAX_BURN_RATE_MONTHS = 12   # 현금이 N개월 이하로 남으면 경고
    MIN_INTEREST_COVERAGE = 1.5

    def evaluate(self, context: StockAnalysisContext) -> AgentOpinion:
        f = context.fundamentals

        penalty = 0      # 패널티 누적 (높을수록 위험)
        max_penalty = 0
        metrics: dict = {}
        risk_flags: list[str] = []
        strengths: list[str] = []

        # ── 부채 리스크 (30점) ──────────────────────────────────────────────
        # D/E는 자사주매입·누적결손으로 왜곡될 수 있으므로
        # Net Debt / EBITDA를 1차 지표로 사용하고, 데이터 없을 때만 D/E로 폴백.
        #
        # 왜곡 예시:
        #   - 애플: 대규모 바이백 → equity ≈ 0 → D/E 100x+ (실제론 안전)
        #   - 누적결손 기업: equity 음수 → D/E 음수 (부채 많아도 수치상 낮음)
        #
        # Net Debt = Total Debt - Total Cash
        #   < 0 이면 '순현금' → 부채 리스크 없음
        #   >= 0 이면 Net Debt / EBITDA 로 상환 능력 측정

        debt_to_equity = f.get("debtToEquity")
        total_debt = f.get("totalDebt") or 0
        total_cash = f.get("totalCash") or 0
        ebitda = f.get("ebitda")

        max_penalty += 30

        net_debt = total_debt - total_cash
        net_cash_position = net_debt < 0

        if net_cash_position:
            # 현금이 부채를 초과 → 실질 부채 리스크 없음
            metrics["net_debt_b"] = round(net_debt / 1e9, 2)
            strengths.append(
                f"순현금 포지션 (현금 {total_cash/1e9:.1f}B > 부채 {total_debt/1e9:.1f}B)"
            )
            if debt_to_equity and debt_to_equity > 10:
                metrics["de_skipped"] = (
                    f"D/E {debt_to_equity:.0f}x는 자사주매입 왜곡 — Net Debt 기준 평가로 대체"
                )

        elif ebitda and ebitda > 0:
            # Net Debt / EBITDA: 실질 상환 능력 지표
            nd_ebitda = net_debt / ebitda
            metrics["net_debt_to_ebitda"] = round(nd_ebitda, 2)
            metrics["net_debt_b"] = round(net_debt / 1e9, 2)

            if nd_ebitda < 1.0:
                strengths.append(f"Net Debt/EBITDA {nd_ebitda:.1f}x — 부채 상환 여유 충분")
            elif nd_ebitda < 2.0:
                penalty += 5
            elif nd_ebitda < 3.0:
                penalty += 12
                risk_flags.append(f"Net Debt/EBITDA {nd_ebitda:.1f}x — 다소 높음")
            elif nd_ebitda < 5.0:
                penalty += 22
                risk_flags.append(f"Net Debt/EBITDA {nd_ebitda:.1f}x — 위험 수준")
            else:
                penalty += 30
                risk_flags.append(f"Net Debt/EBITDA {nd_ebitda:.1f}x — 매우 위험")

            # 고D/E인 경우 왜곡 여부 메모 추가
            if debt_to_equity and debt_to_equity > 10:
                metrics["de_note"] = (
                    f"D/E {debt_to_equity:.0f}x — 자사주매입 왜곡 가능성, Net Debt/EBITDA로 평가"
                )

        else:
            # EBITDA 없음(적자 기업 등) → D/E 원래 방식으로 폴백
            if debt_to_equity is not None:
                metrics["debt_to_equity"] = round(debt_to_equity, 2)
                if debt_to_equity > self.MAX_DEBT_TO_EQUITY:
                    penalty += 30
                    risk_flags.append(f"고부채 D/E {debt_to_equity:.1f}x")
                elif debt_to_equity > 2.0:
                    penalty += 20
                    risk_flags.append(f"높은 부채비율 D/E {debt_to_equity:.1f}x")
                elif debt_to_equity > 1.0:
                    penalty += 10
                elif debt_to_equity <= 0.3:
                    strengths.append(f"낮은 부채비율 D/E {debt_to_equity:.1f}x")

        # ── 유동성 리스크 (25점) ─────────────────────────────────────────────
        # current ratio < 1.0이라도 FCF가 충분하면 실질 유동성 위기가 아닐 수 있음.
        # 예: 애플 current ratio ~0.97이지만 연 FCF $100B+ → 실질 유동성 문제 없음.
        # FCF / 매출 > 15% 이면 current ratio 0.8~1.0 패널티를 대폭 경감.
        current_ratio = f.get("currentRatio")
        fcf_for_liquidity = f.get("freeCashflow")
        revenue_for_liquidity = f.get("totalRevenue")
        fcf_margin = (
            fcf_for_liquidity / revenue_for_liquidity
            if (fcf_for_liquidity and revenue_for_liquidity and revenue_for_liquidity > 0)
            else None
        )

        if current_ratio is not None:
            max_penalty += 25
            metrics["current_ratio"] = round(current_ratio, 2)

            if current_ratio < self.MIN_CURRENT_RATIO:
                # 0.8 미만: FCF가 강해도 유동성 위기로 판단
                penalty += 25
                risk_flags.append(f"유동성 위기 current ratio {current_ratio:.2f}x")

            elif current_ratio < 1.0:
                # 0.8 ~ 1.0: FCF 여력으로 보정
                if fcf_margin and fcf_margin > 0.15:
                    penalty += 3
                    metrics["current_ratio_note"] = (
                        f"FCF마진 {fcf_margin*100:.0f}%로 유동성 리스크 경감"
                    )
                elif fcf_margin and fcf_margin > 0.05:
                    penalty += 8
                else:
                    penalty += 15
                    risk_flags.append(f"유동성 주의 current ratio {current_ratio:.2f}x")

            elif current_ratio < 1.5:
                penalty += 5
            else:
                strengths.append(f"양호한 유동성 current ratio {current_ratio:.1f}x")

        # ── 이자 보상 배율 (20점) ────────────────────────────────────────────
        ebit = f.get("ebit")
        interest_expense = f.get("interestExpense")
        if ebit is not None and interest_expense and abs(interest_expense) > 0:
            coverage = abs(ebit / interest_expense)
            max_penalty += 20
            metrics["interest_coverage"] = round(coverage, 1)
            if coverage < self.MIN_INTEREST_COVERAGE:
                penalty += 20
                risk_flags.append(f"이자 보상 불충분 {coverage:.1f}x (임계값 {self.MIN_INTEREST_COVERAGE}x)")
            elif coverage < 3.0:
                penalty += 10
                risk_flags.append(f"이자 보상 여유 부족 {coverage:.1f}x")
            elif coverage >= 10.0:
                strengths.append(f"이자 보상 충분 {coverage:.1f}x")

        # ── FCF 적자 / 현금 소진율 (15점) ────────────────────────────────────
        fcf = f.get("freeCashflow")
        cash = f.get("totalCash")

        if fcf is not None and fcf < 0:
            max_penalty += 15
            metrics["fcf"] = fcf
            if cash and cash > 0:
                burn_months = (cash / abs(fcf)) * 12
                metrics["cash_runway_months"] = round(burn_months, 1)
                if burn_months < self.MAX_BURN_RATE_MONTHS:
                    penalty += 15
                    risk_flags.append(
                        f"현금 소진 위험 — 잔여 {burn_months:.0f}개월 runway"
                    )
                elif burn_months < 24:
                    penalty += 8
                    risk_flags.append(f"현금 소진 주의 — {burn_months:.0f}개월 runway")
                else:
                    penalty += 3
            else:
                penalty += 10
                risk_flags.append("FCF 적자 + 현금 정보 없음")
        elif fcf and fcf > 0:
            strengths.append(f"플러스 FCF {fcf:,.0f}")

        # ── 수익성 적자 (10점) ──────────────────────────────────────────────
        net_income = f.get("netIncomeToCommon")
        if net_income is not None and net_income < 0:
            max_penalty += 10
            metrics["net_income"] = net_income
            penalty += 8
            risk_flags.append(f"순손실 기업 ({net_income:,.0f})")

        # ── 종합 리스크 판정 ─────────────────────────────────────────────────
        if max_penalty == 0:
            return AgentOpinion(
                agent_name=self.name,
                signal=Signal.WATCH,
                confidence=0.3,
                rationale="리스크 평가 데이터 불충분",
                key_metrics=metrics,
                risk_flags=["리스크 데이터 없음"],
            )

        risk_pct = penalty / max_penalty
        metrics["risk_score"] = f"{penalty}/{max_penalty} ({risk_pct*100:.0f}%)"

        # 리스크 낮을수록 매수 우호적
        if risk_pct >= 0.75:
            signal = Signal.AVOID
            confidence = min(0.80 + (risk_pct - 0.75) * 0.8, 0.95)
            rationale = (
                f"심각한 리스크 발견 ({risk_pct*100:.0f}%). "
                f"{'; '.join(risk_flags[:2]) if risk_flags else '투자 부적합 리스크'}."
            )
        elif risk_pct >= 0.50:
            signal = Signal.PASS
            confidence = 0.65
            rationale = (
                f"주요 리스크 존재 ({risk_pct*100:.0f}%). "
                f"{risk_flags[0] if risk_flags else '리스크 주의 필요'}."
            )
        elif risk_pct >= 0.25:
            signal = Signal.WATCH
            confidence = 0.55
            rationale = f"보통 수준의 리스크 ({risk_pct*100:.0f}%). 모니터링 권장."
        elif risk_pct >= 0.10:
            signal = Signal.BUY
            confidence = 0.70
            rationale = (
                f"낮은 리스크 ({risk_pct*100:.0f}%). "
                f"{strengths[0] if strengths else '재무 건전성 양호'}."
            )
        else:
            signal = Signal.BUY
            confidence = 0.85
            rationale = (
                f"매우 낮은 리스크 ({risk_pct*100:.0f}%). "
                f"{', '.join(strengths[:2]) if strengths else '안정적인 재무 구조'}."
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
