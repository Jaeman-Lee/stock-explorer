"""밸류에이션 평가 에이전트.

평가 기준: P/E, P/B, PEG, EV/EBITDA, P/FCF, 역사적 밸류에이션 밴드.
fin-advisor의 value_investor 관점을 계승 + 확장.
"""

from __future__ import annotations

from src.agents.base_agent import StockAgent
from src.agents.models import AgentOpinion, Signal, StockAnalysisContext


class ValuationAgent(StockAgent):
    """주가 대비 가치 평가 에이전트."""

    name = "valuation-analyst"
    description = "P/E·P/B·PEG·EV/EBITDA 기반 현재 주가 매력도 평가"

    def evaluate(self, context: StockAnalysisContext) -> AgentOpinion:
        f = context.fundamentals
        hist = context.historical_multiples
        peers = context.sector_peers

        score = 0
        max_score = 0
        metrics: dict = {}
        strengths: list[str] = []
        risk_flags: list[str] = []

        # ── P/E 평가 (25점) ─────────────────────────────────────────────────
        pe = f.get("trailingPE") or f.get("forwardPE")
        pe_label = "trailing P/E" if f.get("trailingPE") else "forward P/E"
        sector_avg_pe = self._avg(peers, "pe") or 25.0
        hist_avg_pe = hist.get("avg_pe") or sector_avg_pe

        if pe is not None and pe > 0:
            max_score += 25
            metrics[pe_label] = round(pe, 1)
            metrics["sector_avg_pe"] = round(sector_avg_pe, 1)
            discount_vs_sector = (sector_avg_pe - pe) / sector_avg_pe

            if discount_vs_sector >= 0.25:
                score += 25
                strengths.append(f"{pe_label} {pe:.1f}x — 섹터 평균 대비 {discount_vs_sector*100:.0f}% 할인")
            elif discount_vs_sector >= 0.10:
                score += 18
                strengths.append(f"{pe_label} {pe:.1f}x — 섹터 평균 대비 소폭 할인")
            elif discount_vs_sector >= -0.10:
                score += 12
            elif discount_vs_sector >= -0.30:
                score += 6
                risk_flags.append(f"{pe_label} {pe:.1f}x — 섹터 대비 {-discount_vs_sector*100:.0f}% 프리미엄")
            else:
                risk_flags.append(f"{pe_label} {pe:.1f}x — 심각한 고평가")
        elif pe is not None and pe <= 0:
            risk_flags.append("적자 기업 (P/E 음수)")

        # ── P/B 평가 (15점) ─────────────────────────────────────────────────
        pb = f.get("priceToBook")
        if pb is not None and pb > 0:
            max_score += 15
            metrics["price_to_book"] = round(pb, 2)
            if pb < 1.0:
                score += 15
                strengths.append(f"P/B {pb:.1f}x — 장부가 이하 (자산 안전마진)")
            elif pb < 2.0:
                score += 10
            elif pb < 4.0:
                score += 6
            elif pb < 8.0:
                score += 3
            else:
                risk_flags.append(f"P/B {pb:.1f}x 고평가")

        # ── PEG 평가 (20점) ─────────────────────────────────────────────────
        peg = f.get("pegRatio")
        if peg is not None and peg > 0:
            max_score += 20
            metrics["peg_ratio"] = round(peg, 2)
            if peg < 0.8:
                score += 20
                strengths.append(f"PEG {peg:.2f} — 성장성 대비 저평가")
            elif peg < 1.2:
                score += 14
                strengths.append(f"PEG {peg:.2f} — 성장성 대비 적정 가격")
            elif peg < 1.8:
                score += 8
            elif peg < 2.5:
                score += 4
            else:
                risk_flags.append(f"PEG {peg:.2f} — 성장성 대비 고평가")

        # ── P/FCF 평가 (20점) ───────────────────────────────────────────────
        mktcap = f.get("marketCap")
        fcf = f.get("freeCashflow")
        if mktcap and fcf and fcf > 0:
            p_fcf = mktcap / fcf
            max_score += 20
            metrics["price_to_fcf"] = round(p_fcf, 1)
            if p_fcf < 15:
                score += 20
                strengths.append(f"P/FCF {p_fcf:.1f}x — 현금흐름 대비 저평가")
            elif p_fcf < 25:
                score += 14
            elif p_fcf < 35:
                score += 8
            elif p_fcf < 50:
                score += 4
            else:
                risk_flags.append(f"P/FCF {p_fcf:.1f}x 높음")
        elif fcf is not None and fcf <= 0:
            risk_flags.append("FCF 마이너스 (잉여현금흐름 없음)")

        # ── EV/EBITDA (20점) ────────────────────────────────────────────────
        ev_ebitda = f.get("enterpriseToEbitda")
        if ev_ebitda is not None and ev_ebitda > 0:
            max_score += 20
            metrics["ev_to_ebitda"] = round(ev_ebitda, 1)
            sector_avg_ebitda = self._avg(peers, "ev_ebitda") or 15.0
            discount = (sector_avg_ebitda - ev_ebitda) / sector_avg_ebitda

            if discount >= 0.20:
                score += 20
                strengths.append(f"EV/EBITDA {ev_ebitda:.1f}x — 섹터 대비 저평가")
            elif discount >= 0.05:
                score += 14
            elif discount >= -0.10:
                score += 9
            elif discount >= -0.25:
                score += 4
            else:
                risk_flags.append(f"EV/EBITDA {ev_ebitda:.1f}x — 섹터 대비 고평가")

        # ── 종합 판정 ───────────────────────────────────────────────────────
        if max_score == 0:
            return AgentOpinion(
                agent_name=self.name,
                signal=Signal.WATCH,
                confidence=0.2,
                rationale="밸류에이션 데이터 불충분",
                key_metrics=metrics,
                risk_flags=["밸류에이션 데이터 없음"],
            )

        pct = score / max_score
        metrics["valuation_score"] = f"{score}/{max_score} ({pct*100:.0f}%)"

        if pct >= 0.75:
            signal = Signal.STRONG_BUY
            confidence = min(0.80 + (pct - 0.75) * 0.6, 0.95)
            rationale = (
                f"매력적인 밸류에이션 ({pct*100:.0f}%). "
                f"{', '.join(strengths[:2]) if strengths else '복수 지표에서 저평가 확인'}."
            )
        elif pct >= 0.55:
            signal = Signal.BUY
            confidence = 0.60 + (pct - 0.55) * 1.0
            rationale = (
                f"합리적인 가격 수준 ({pct*100:.0f}%). "
                f"{strengths[0] if strengths else '밸류에이션 적정'}."
            )
        elif pct >= 0.35:
            signal = Signal.WATCH
            confidence = 0.45
            rationale = (
                f"밸류에이션 다소 부담 ({pct*100:.0f}%). "
                f"조정 시 재평가 권장."
            )
        elif pct >= 0.15:
            signal = Signal.PASS
            confidence = 0.65
            rationale = (
                f"고평가 상태 ({pct*100:.0f}%). "
                f"{risk_flags[0] if risk_flags else '현재 가격 메리트 부족'}."
            )
        else:
            signal = Signal.AVOID
            confidence = 0.75
            rationale = (
                f"심각한 고평가 ({pct*100:.0f}%). "
                f"{'; '.join(risk_flags[:2]) if risk_flags else '밸류에이션 투자 부적합'}."
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

    @staticmethod
    def _avg(peers: list[dict], key: str) -> float | None:
        vals = [p[key] for p in peers if p.get(key) and p[key] > 0]
        return sum(vals) / len(vals) if vals else None
