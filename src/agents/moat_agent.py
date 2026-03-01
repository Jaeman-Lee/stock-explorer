"""경쟁 해자(Moat) 평가 에이전트.

평가 기준: 매출총이익률 추이(가격결정력), ROIC vs 업종 평균,
시장 지위, 브랜드/IP 투자, 고객 유지력.
"""

from __future__ import annotations

from src.agents.base_agent import StockAgent
from src.agents.models import AgentOpinion, Signal, StockAnalysisContext


class MoatAgent(StockAgent):
    """경쟁우위(해자) 지속성 평가 에이전트."""

    name = "moat-analyst"
    description = "매출총이익률 추이·ROIC·시장 지위·브랜드/IP 기반 경쟁 해자 평가"

    def evaluate(self, context: StockAnalysisContext) -> AgentOpinion:
        f = context.fundamentals
        history = context.financial_history
        peers = context.sector_peers

        score = 0
        max_score = 0
        metrics: dict = {}
        strengths: list[str] = []
        risk_flags: list[str] = []

        # ── 매출총이익률 수준 + 추이 (25점) ─────────────────────────────────
        gross_margin = f.get("grossMargins")
        if gross_margin is not None:
            max_score += 15
            metrics["gross_margin_pct"] = round(gross_margin * 100, 1)
            peer_gm = self._avg(peers, "gross_margin") or 0.35
            gm_premium = gross_margin - peer_gm

            if gm_premium >= 0.15:
                score += 15
                strengths.append(
                    f"매출총이익률 {gross_margin*100:.0f}% — 동종 대비 {gm_premium*100:.0f}%p 우위 (강한 가격결정력)"
                )
            elif gm_premium >= 0.05:
                score += 11
                strengths.append(f"매출총이익률 {gross_margin*100:.0f}% — 업종 상위권")
            elif gm_premium >= -0.05:
                score += 7
            elif gm_premium >= -0.15:
                score += 3
                risk_flags.append(f"매출총이익률 업종 하위 ({gross_margin*100:.0f}% vs 동종 {peer_gm*100:.0f}%)")
            else:
                risk_flags.append(f"매출총이익률 매우 낮음 ({gross_margin*100:.0f}%)")

        # 매출총이익률 추이 (확장 중인지)
        gm_trend = self._margin_trend(history, "gross_margin")
        if gm_trend is not None:
            max_score += 10
            metrics["gross_margin_trend"] = gm_trend
            if gm_trend == "expanding":
                score += 10
                strengths.append("매출총이익률 확장 추이 — 가격결정력 강화")
            elif gm_trend == "stable":
                score += 7
            elif gm_trend == "contracting":
                score += 3
                risk_flags.append("매출총이익률 수축 추이 — 경쟁 압박 또는 원가 상승")
            else:
                score += 1

        # ── ROIC (25점) ──────────────────────────────────────────────────────
        roic = f.get("returnOnAssets")   # ROIC 없으면 ROA로 대체
        roe = f.get("returnOnEquity")

        if roe is not None:
            max_score += 15
            metrics["roe_pct"] = round(roe * 100, 1)
            peer_roe = self._avg(peers, "roe") or 0.12
            if roe >= 0.25:
                score += 15
                strengths.append(f"ROE {roe*100:.0f}% — 자본 효율성 탁월 (해자 시사)")
            elif roe >= 0.15:
                score += 11
                strengths.append(f"ROE {roe*100:.0f}% — 업종 상위권")
            elif roe >= peer_roe:
                score += 7
            elif roe >= 0.0:
                score += 3
            else:
                risk_flags.append(f"ROE 마이너스 ({roe*100:.1f}%)")

        if roic is not None:
            max_score += 10
            metrics["roa_pct"] = round(roic * 100, 1)
            if roic >= 0.15:
                score += 10
                strengths.append(f"ROA {roic*100:.0f}% — 자산 운용 우수")
            elif roic >= 0.08:
                score += 7
            elif roic >= 0.03:
                score += 4
            else:
                risk_flags.append(f"ROA 낮음 ({roic*100:.1f}%)")

        # ── R&D / 브랜드 투자 (15점) ─────────────────────────────────────────
        rd_pct = self._safe_ratio(f.get("researchAndDevelopment"), f.get("totalRevenue"))
        if rd_pct is not None:
            max_score += 10
            metrics["rd_to_revenue_pct"] = round(rd_pct * 100, 1)
            if rd_pct >= 0.15:
                score += 10
                strengths.append(f"높은 R&D 투자 비중 {rd_pct*100:.0f}% — 기술 해자 강화")
            elif rd_pct >= 0.08:
                score += 7
            elif rd_pct >= 0.03:
                score += 4
            else:
                score += 2  # R&D 불필요 업종(소비재 등)도 있음

        # 영업비용 레버리지 (매출 성장 > 비용 성장 = 규모의 경제)
        op_leverage = self._operating_leverage(history)
        if op_leverage is not None:
            max_score += 5
            metrics["operating_leverage"] = op_leverage
            if op_leverage >= 1.3:
                score += 5
                strengths.append(f"영업 레버리지 {op_leverage:.1f}x — 규모의 경제 작동")
            elif op_leverage >= 1.0:
                score += 3
            else:
                score += 1
                risk_flags.append(f"비용 증가 매출 초과 ({op_leverage:.1f}x)")

        # ── 시장 지위 (동종 비교) (20점) ────────────────────────────────────
        mktcap = f.get("marketCap")
        if mktcap and peers:
            peer_caps = [p.get("market_cap") for p in peers if p.get("market_cap")]
            if peer_caps:
                max_score += 20
                rank_pct = sum(1 for c in peer_caps if c < mktcap) / len(peer_caps)
                metrics["market_cap_rank_pct"] = round(rank_pct * 100, 0)
                if rank_pct >= 0.80:
                    score += 20
                    strengths.append("시장 지위 상위 20% — 업계 리더")
                elif rank_pct >= 0.60:
                    score += 14
                elif rank_pct >= 0.40:
                    score += 9
                elif rank_pct >= 0.20:
                    score += 5
                else:
                    score += 2
                    risk_flags.append("시장 지위 하위권")

        # ── 종합 판정 ───────────────────────────────────────────────────────
        if max_score == 0:
            return AgentOpinion(
                agent_name=self.name,
                signal=Signal.WATCH,
                confidence=0.2,
                rationale="해자 평가 데이터 불충분",
                key_metrics=metrics,
                risk_flags=["해자 데이터 없음"],
            )

        pct = score / max_score
        metrics["moat_score"] = f"{score}/{max_score} ({pct*100:.0f}%)"

        if pct >= 0.75:
            signal = Signal.STRONG_BUY
            confidence = min(0.82 + (pct - 0.75) * 0.52, 0.95)
            rationale = (
                f"강한 경쟁 해자 확인 ({pct*100:.0f}%). "
                f"{', '.join(strengths[:2]) if strengths else '복수 지표에서 해자 우위'}."
            )
        elif pct >= 0.55:
            signal = Signal.BUY
            confidence = 0.60 + (pct - 0.55) * 1.1
            rationale = (
                f"어느 정도의 경쟁우위 ({pct*100:.0f}%). "
                f"{strengths[0] if strengths else '일부 해자 요소 확인'}."
            )
        elif pct >= 0.35:
            signal = Signal.WATCH
            confidence = 0.50
            rationale = f"해자 약하거나 불명확 ({pct*100:.0f}%). 추가 조사 필요."
        elif pct >= 0.15:
            signal = Signal.PASS
            confidence = 0.60
            rationale = (
                f"해자 취약 ({pct*100:.0f}%). "
                f"{risk_flags[0] if risk_flags else '경쟁우위 부재'}."
            )
        else:
            signal = Signal.AVOID
            confidence = 0.70
            rationale = (
                f"경쟁우위 없음 ({pct*100:.0f}%). "
                f"{'; '.join(risk_flags[:2]) if risk_flags else '해자 없는 경쟁적 업종'}."
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
        vals = [p[key] for p in peers if p.get(key)]
        return sum(vals) / len(vals) if vals else None

    @staticmethod
    def _margin_trend(history: list[dict], key: str) -> str | None:
        vals = [h.get(key) for h in history if h.get(key) is not None]
        if len(vals) < 3:
            return None
        recent, older = vals[-1], vals[-3]
        diff = recent - older
        if diff >= 0.03:
            return "expanding"
        elif diff >= -0.02:
            return "stable"
        else:
            return "contracting"

    @staticmethod
    def _operating_leverage(history: list[dict]) -> float | None:
        """매출 성장률 / 영업비용 성장률. > 1이면 규모의 경제 작동."""
        if len(history) < 2:
            return None
        prev, curr = history[-2], history[-1]
        rev_prev = prev.get("revenue", 0)
        rev_curr = curr.get("revenue", 0)
        cost_prev = prev.get("operating_expense", 0)
        cost_curr = curr.get("operating_expense", 0)
        if not all([rev_prev, rev_curr, cost_prev, cost_curr]):
            return None
        rev_growth = (rev_curr - rev_prev) / abs(rev_prev)
        cost_growth = (cost_curr - cost_prev) / abs(cost_prev)
        if cost_growth == 0:
            return None
        return rev_growth / cost_growth
