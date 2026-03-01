"""기술적 모멘텀 평가 에이전트.

fin-advisor의 momentum_trader.py를 그대로 계승.
RSI, MACD, SMA, 볼린저밴드 기반 진입 타이밍 평가.
"""

from __future__ import annotations

from src.agents.base_agent import StockAgent
from src.agents.models import AgentOpinion, Signal, StockAnalysisContext


class MomentumAgent(StockAgent):
    """기술적 분석 기반 진입 타이밍 평가 에이전트.

    fin-advisor momentum_trader.py 패턴을 stock-explorer에 맞게 이식.
    """

    name = "momentum-analyst"
    description = "RSI·MACD·SMA·볼린저밴드 기반 기술적 진입 타이밍 평가"

    def evaluate(self, context: StockAnalysisContext) -> AgentOpinion:
        ind = self._latest_indicators(context)

        if not ind or ind.get("close") is None:
            return AgentOpinion(
                agent_name=self.name,
                signal=Signal.WATCH,
                confidence=0.2,
                rationale="시장 데이터 없음 — 기술적 분석 불가",
                key_metrics={},
                risk_flags=["시장 데이터 부재"],
            )

        score = 0
        max_score = 0
        metrics: dict = {}
        strengths: list[str] = []
        risk_flags: list[str] = []

        close = ind["close"]

        # ── RSI 평가 (25점) ──────────────────────────────────────────────────
        rsi = ind.get("rsi_14")
        if rsi is not None:
            max_score += 25
            metrics["rsi_14"] = round(rsi, 1)
            if rsi <= 30:
                score += 25
                strengths.append(f"RSI {rsi:.0f} — 과매도 구간 (반등 기대)")
            elif rsi <= 45:
                score += 18
                strengths.append(f"RSI {rsi:.0f} — 저RSI 진입 기회")
            elif rsi <= 55:
                score += 14  # 중립
            elif rsi <= 65:
                score += 8
            elif rsi <= 70:
                score += 4
                risk_flags.append(f"RSI {rsi:.0f} — 과매수 접근")
            else:
                risk_flags.append(f"RSI {rsi:.0f} — 과매수 구간")

        # ── MACD 평가 (25점) ─────────────────────────────────────────────────
        macd = ind.get("macd")
        macd_signal = ind.get("macd_signal")
        macd_hist = ind.get("macd_hist")

        if macd is not None and macd_signal is not None:
            max_score += 25
            metrics["macd"] = round(macd, 3)
            metrics["macd_signal"] = round(macd_signal, 3)
            if macd_hist is not None:
                metrics["macd_hist"] = round(macd_hist, 3)

            if macd > macd_signal and macd_hist and macd_hist > 0:
                # 골든크로스 또는 강세 유지
                score += 20
                strengths.append("MACD 골든크로스 또는 강세 구간")
                # 히스토그램 확장 여부
                prev_data = context.market_data[:-1] if len(context.market_data) > 1 else []
                if prev_data:
                    prev_hist = prev_data[-1].get("macd_hist", 0) or 0
                    if macd_hist > prev_hist:
                        score += 5
                        strengths.append("MACD 히스토그램 확장 — 모멘텀 강화")
                    else:
                        score += 2
            elif macd < macd_signal and macd_hist and macd_hist < 0:
                # 데드크로스 또는 약세
                risk_flags.append("MACD 데드크로스 또는 약세 구간")
                score += 5
            else:
                score += 12  # 교차 직전 중립

        # ── SMA 정렬 평가 (25점) ─────────────────────────────────────────────
        sma20 = ind.get("sma_20")
        sma50 = ind.get("sma_50")
        sma200 = ind.get("sma_200")

        if sma20 and sma50 and sma200 and close:
            max_score += 25
            above_20 = close > sma20
            above_50 = close > sma50
            above_200 = close > sma200
            bull_align = sma20 > sma50 > sma200

            metrics["above_sma20"] = above_20
            metrics["above_sma50"] = above_50
            metrics["above_sma200"] = above_200
            metrics["sma_bull_alignment"] = bull_align

            if bull_align and above_20 and above_50 and above_200:
                score += 25
                strengths.append("SMA 완전 정배열 + 이동평균선 상회")
            elif above_50 and above_200:
                score += 18
                strengths.append("SMA50·200 상회 — 중장기 상승 추세")
            elif above_200:
                score += 12
            elif above_50:
                score += 8
            elif not above_200:
                risk_flags.append("200일 이동평균 하회 — 장기 약세")
                score += 4

        # ── 볼린저밴드 위치 (25점) ───────────────────────────────────────────
        bb_upper = ind.get("bb_upper")
        bb_lower = ind.get("bb_lower")
        bb_mid = ind.get("bb_mid")

        if bb_upper and bb_lower and bb_mid and close:
            max_score += 25
            bb_range = bb_upper - bb_lower
            bb_pos = (close - bb_lower) / bb_range if bb_range > 0 else 0.5
            metrics["bollinger_position_pct"] = round(bb_pos * 100, 1)

            if bb_pos <= 0.15:
                score += 25
                strengths.append(f"볼린저 하단 근접 ({bb_pos*100:.0f}%) — 과매도 반등 구간")
            elif bb_pos <= 0.35:
                score += 18
                strengths.append(f"볼린저 하단부 ({bb_pos*100:.0f}%) — 저점 매수 기회")
            elif bb_pos <= 0.65:
                score += 14  # 중앙부 중립
            elif bb_pos <= 0.85:
                score += 7
            else:
                risk_flags.append(f"볼린저 상단 근접 ({bb_pos*100:.0f}%) — 과매수 주의")
                score += 3

        # ── 종합 판정 ───────────────────────────────────────────────────────
        if max_score == 0:
            return AgentOpinion(
                agent_name=self.name,
                signal=Signal.WATCH,
                confidence=0.3,
                rationale="기술적 지표 데이터 부족",
                key_metrics=metrics,
                risk_flags=["기술지표 데이터 없음"],
            )

        pct = score / max_score
        metrics["momentum_score"] = f"{score}/{max_score} ({pct*100:.0f}%)"

        if pct >= 0.75:
            signal = Signal.STRONG_BUY
            confidence = min(0.80 + (pct - 0.75) * 0.6, 0.92)
            rationale = (
                f"강한 기술적 매수 신호 ({pct*100:.0f}%). "
                f"{', '.join(strengths[:2]) if strengths else '복수 지표 매수 신호'}."
            )
        elif pct >= 0.55:
            signal = Signal.BUY
            confidence = 0.60 + (pct - 0.55) * 1.0
            rationale = (
                f"기술적 매수 우세 ({pct*100:.0f}%). "
                f"{strengths[0] if strengths else '기술적 지표 양호'}."
            )
        elif pct >= 0.40:
            signal = Signal.WATCH
            confidence = 0.50
            rationale = f"기술적 중립 ({pct*100:.0f}%). 추세 방향 확인 후 진입."
        elif pct >= 0.25:
            signal = Signal.PASS
            confidence = 0.55
            rationale = (
                f"기술적 약세 ({pct*100:.0f}%). "
                f"{risk_flags[0] if risk_flags else '기술적 진입 타이밍 부적절'}."
            )
        else:
            signal = Signal.AVOID
            confidence = 0.70
            rationale = (
                f"기술적 강한 하락 신호 ({pct*100:.0f}%). "
                f"{'; '.join(risk_flags[:2]) if risk_flags else '기술적 진입 회피'}."
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
