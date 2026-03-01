"""재무 기반 분석 에이전트.

평가 기준: 수익성, 성장성, 재무건전성, 현금흐름 품질.
fin-advisor의 value_investor + growth_investor 관점을 통합.
"""

from __future__ import annotations

from src.agents.base_agent import StockAgent
from src.agents.models import AgentOpinion, Signal, StockAnalysisContext


class FundamentalAgent(StockAgent):
    """재무제표 기반 기업 품질 평가 에이전트."""

    name = "fundamental-analyst"
    description = "수익성·성장성·재무건전성·현금흐름 품질 종합 평가"

    def evaluate(self, context: StockAnalysisContext) -> AgentOpinion:
        f = context.fundamentals
        history = context.financial_history

        score = 0
        max_score = 0
        metrics: dict = {}
        strengths: list[str] = []
        risk_flags: list[str] = []

        # ── 수익성 (30점) ───────────────────────────────────────────────────
        gross_margin = f.get("grossMargins")
        op_margin = f.get("operatingMargins")
        net_margin = f.get("profitMargins")

        if gross_margin is not None:
            max_score += 10
            metrics["gross_margin_pct"] = round(gross_margin * 100, 1)
            if gross_margin >= 0.50:
                score += 10
                strengths.append(f"높은 매출총이익률 {gross_margin*100:.0f}% (경쟁우위 시사)")
            elif gross_margin >= 0.35:
                score += 6
            elif gross_margin >= 0.20:
                score += 3
            else:
                risk_flags.append(f"낮은 매출총이익률 {gross_margin*100:.0f}%")

        if op_margin is not None:
            max_score += 10
            metrics["operating_margin_pct"] = round(op_margin * 100, 1)
            if op_margin >= 0.20:
                score += 10
                strengths.append(f"우수한 영업이익률 {op_margin*100:.0f}%")
            elif op_margin >= 0.10:
                score += 6
            elif op_margin >= 0.0:
                score += 3
            else:
                risk_flags.append(f"영업손실 상태 ({op_margin*100:.1f}%)")

        if net_margin is not None:
            max_score += 10
            metrics["net_margin_pct"] = round(net_margin * 100, 1)
            if net_margin >= 0.15:
                score += 10
            elif net_margin >= 0.05:
                score += 6
            elif net_margin >= 0.0:
                score += 3
            else:
                risk_flags.append(f"순손실 ({net_margin*100:.1f}%)")

        # ── 성장성 (30점) ───────────────────────────────────────────────────
        rev_growth = f.get("revenueGrowth")
        earnings_growth = f.get("earningsGrowth")

        if rev_growth is not None:
            max_score += 15
            metrics["revenue_growth_yoy_pct"] = round(rev_growth * 100, 1)
            if rev_growth >= 0.25:
                score += 15
                strengths.append(f"고성장 매출 +{rev_growth*100:.0f}% YoY")
            elif rev_growth >= 0.15:
                score += 10
            elif rev_growth >= 0.05:
                score += 6
            elif rev_growth >= 0.0:
                score += 3
            else:
                risk_flags.append(f"매출 역성장 {rev_growth*100:.1f}%")

        if earnings_growth is not None:
            max_score += 15
            metrics["earnings_growth_yoy_pct"] = round(earnings_growth * 100, 1)
            if earnings_growth >= 0.20:
                score += 15
                strengths.append(f"이익 고성장 +{earnings_growth*100:.0f}% YoY")
            elif earnings_growth >= 0.10:
                score += 10
            elif earnings_growth >= 0.0:
                score += 5
            else:
                risk_flags.append(f"이익 역성장 {earnings_growth*100:.1f}%")

        # ── 재무 건전성 (20점) ──────────────────────────────────────────────
        # D/E는 자사주매입으로 왜곡될 수 있어 Net Debt/EBITDA 우선 사용.
        # current ratio < 1.0은 FCF가 충분하면 실질 리스크가 아닐 수 있음.
        total_debt = f.get("totalDebt") or 0
        total_cash = f.get("totalCash") or 0
        ebitda = f.get("ebitda")
        debt_to_equity = f.get("debtToEquity")
        current_ratio = f.get("currentRatio")
        fcf_health = f.get("freeCashflow")
        revenue_health = f.get("totalRevenue")

        # 실질적인 부채 데이터가 있을 때만 해당 섹션 평가
        has_debt_data = total_debt > 0 or debt_to_equity is not None or ebitda is not None
        if has_debt_data:
            max_score += 10
        net_debt = total_debt - total_cash
        if has_debt_data and net_debt < 0:
            # 순현금 포지션
            score += 10
            strengths.append(f"순현금 포지션 ({total_cash/1e9:.1f}B > 부채 {total_debt/1e9:.1f}B)")
            metrics["net_debt_b"] = round(net_debt / 1e9, 2)
        elif ebitda and ebitda > 0:
            nd_ebitda = net_debt / ebitda
            metrics["net_debt_to_ebitda"] = round(nd_ebitda, 2)
            if nd_ebitda < 1.0:
                score += 10
                strengths.append(f"Net Debt/EBITDA {nd_ebitda:.1f}x — 낮은 실질 부채")
            elif nd_ebitda < 2.0:
                score += 7
            elif nd_ebitda < 3.0:
                score += 4
            else:
                risk_flags.append(f"Net Debt/EBITDA {nd_ebitda:.1f}x 높음")
            if debt_to_equity and debt_to_equity > 10:
                metrics["de_note"] = f"D/E {debt_to_equity:.0f}x — 자사주매입 왜곡 가능, Net Debt 기준 평가"
        elif debt_to_equity is not None:
            # EBITDA 없을 때만 D/E 폴백
            metrics["debt_to_equity"] = round(debt_to_equity, 2)
            if debt_to_equity < 0.5:
                score += 10
                strengths.append(f"낮은 부채비율 D/E {debt_to_equity:.1f}x")
            elif debt_to_equity < 1.0:
                score += 7
            elif debt_to_equity < 2.0:
                score += 4
            else:
                risk_flags.append(f"고부채 D/E {debt_to_equity:.1f}x")

        if current_ratio is not None:
            max_score += 10
            metrics["current_ratio"] = round(current_ratio, 2)
            fcf_margin = (
                fcf_health / revenue_health
                if (fcf_health and revenue_health and revenue_health > 0)
                else None
            )
            if current_ratio >= 2.0:
                score += 10
            elif current_ratio >= 1.5:
                score += 7
            elif current_ratio >= 1.0:
                score += 4
            elif fcf_margin and fcf_margin > 0.15:
                # current ratio < 1.0이지만 FCF가 충분하면 부분 점수
                score += 3
                metrics["current_ratio_note"] = f"FCF마진 {fcf_margin*100:.0f}%로 유동성 보완"
            else:
                risk_flags.append(f"유동성 위험 current ratio {current_ratio:.1f}x")

        # ── 현금흐름 품질 (20점) ────────────────────────────────────────────
        fcf = f.get("freeCashflow")
        net_income = f.get("netIncomeToCommon")
        roe = f.get("returnOnEquity")

        if roe is not None:
            max_score += 10
            metrics["roe_pct"] = round(roe * 100, 1)
            if roe >= 0.20:
                score += 10
                strengths.append(f"높은 ROE {roe*100:.0f}% (자본효율성 우수)")
            elif roe >= 0.12:
                score += 7
            elif roe >= 0.0:
                score += 3
            else:
                risk_flags.append(f"마이너스 ROE {roe*100:.1f}%")

        if fcf is not None and net_income and net_income != 0:
            max_score += 10
            fcf_quality = fcf / abs(net_income)
            metrics["fcf_to_net_income"] = round(fcf_quality, 2)
            if fcf_quality >= 1.0:
                score += 10
                strengths.append(f"FCF/순이익 {fcf_quality:.1f}x — 이익 현금 전환 우수")
            elif fcf_quality >= 0.7:
                score += 7
            elif fcf_quality >= 0.3:
                score += 4
            else:
                risk_flags.append(f"낮은 FCF 전환율 {fcf_quality:.1f}x")

        # ── 종합 판정 ───────────────────────────────────────────────────────
        if max_score == 0:
            return AgentOpinion(
                agent_name=self.name,
                signal=Signal.WATCH,
                confidence=0.2,
                rationale="재무 데이터 불충분 — 추가 조사 필요",
                key_metrics=metrics,
                risk_flags=["재무 데이터 없음"],
            )

        pct = score / max_score
        metrics["fundamental_score"] = f"{score}/{max_score} ({pct*100:.0f}%)"

        if pct >= 0.80:
            signal, confidence = Signal.STRONG_BUY, min(0.85 + (pct - 0.80) * 0.5, 0.95)
            rationale = (
                f"펀더멘탈 최상위권 ({pct*100:.0f}%). "
                f"{', '.join(strengths[:2]) if strengths else '전반적으로 우수한 재무 구조'}."
            )
        elif pct >= 0.65:
            signal, confidence = Signal.BUY, 0.65 + (pct - 0.65) * 1.33
            rationale = (
                f"양호한 펀더멘탈 ({pct*100:.0f}%). "
                f"{strengths[0] if strengths else '수익성·성장성 양호'}."
            )
        elif pct >= 0.45:
            signal, confidence = Signal.WATCH, 0.50
            rationale = (
                f"펀더멘탈 보통 수준 ({pct*100:.0f}%). "
                f"개선 추이 확인 필요."
            )
        elif pct >= 0.25:
            signal, confidence = Signal.PASS, 0.60
            rationale = (
                f"펀더멘탈 미흡 ({pct*100:.0f}%). "
                f"{risk_flags[0] if risk_flags else '전반적으로 약한 재무 구조'}."
            )
        else:
            signal, confidence = Signal.AVOID, 0.75
            rationale = (
                f"심각한 재무 약점 ({pct*100:.0f}%). "
                f"{'; '.join(risk_flags[:2]) if risk_flags else '투자 부적합'}."
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
