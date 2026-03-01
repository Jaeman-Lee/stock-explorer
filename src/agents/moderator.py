"""종목 탐험 토론 사회자.

fin-advisor의 moderator.py 패턴을 그대로 계승.
5개 에이전트가 독립 평가 → 교차 반박 → 투표 → 최종 판정.
"""

from __future__ import annotations

import datetime
from collections import Counter

from src.agents.base_agent import StockAgent
from src.agents.fundamental_agent import FundamentalAgent
from src.agents.growth_agent import GrowthAgent
from src.agents.moat_agent import MoatAgent
from src.agents.models import (
    AgentOpinion,
    ExplorationResult,
    NEGATIVE_SIGNALS,
    NEUTRAL_SIGNALS,
    POSITIVE_SIGNALS,
    Rebuttal,
    Signal,
    StockAnalysisContext,
    Urgency,
)
from src.agents.momentum_agent import MomentumAgent
from src.agents.risk_agent import RiskAgent


class ExplorationModerator:
    """5개 에이전트 기반 종목 탐험 토론 사회자.

    Phase 1: 독립 평가 (5 agents)
    Phase 2: 교차 반박 (상충 의견 쌍)
    Phase 3: 투표 집계 (confidence 가중)
    Phase 4: 긴급도 분류 (unanimous / majority / split / red_flag)
    Phase 5: 결과 조립
    """

    def __init__(self) -> None:
        self.agents: list[StockAgent] = [
            FundamentalAgent(),
            ValuationAgentLazy(),   # 지연 임포트 방지를 위한 래퍼
            GrowthAgent(),
            MoatAgent(),
            MomentumAgent(),
            RiskAgent(),
        ]

    def run(self, context: StockAnalysisContext) -> ExplorationResult:
        """전체 탐험 토론 프로세스를 실행한다."""
        # Phase 1: 독립 평가
        opinions = self._collect_opinions(context)

        # Phase 2: 교차 반박
        rebuttals = self._cross_examine(opinions)

        # Phase 3: 투표 집계
        vote_tally = self._tally_votes(opinions)

        # Phase 4: 최종 신호 + 긴급도
        final_signal = self._determine_signal(opinions, vote_tally)
        final_confidence = self._compute_confidence(opinions, final_signal)
        urgency = self._classify_urgency(opinions, vote_tally, final_signal)

        # Phase 5: 결과 조립
        summary = self._build_summary(opinions, final_signal, final_confidence, vote_tally)
        thesis = self._build_thesis(opinions, final_signal)
        key_risks = self._collect_risks(opinions)
        entry_conditions = self._suggest_entry(context, opinions, final_signal)

        return ExplorationResult(
            ticker=context.ticker,
            company_name=context.company_name,
            opinions=opinions,
            rebuttals=rebuttals,
            vote_tally=vote_tally,
            final_signal=final_signal,
            final_confidence=round(final_confidence, 2),
            urgency=urgency,
            summary=summary,
            investment_thesis=thesis,
            key_risks=key_risks,
            entry_conditions=entry_conditions,
            timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        )

    # ── Phase 1: 독립 평가 ──────────────────────────────────────────────────

    def _collect_opinions(self, context: StockAnalysisContext) -> list[AgentOpinion]:
        opinions = []
        for agent in self.agents:
            try:
                opinion = agent.evaluate(context)
                opinions.append(opinion)
            except Exception as exc:  # noqa: BLE001
                # 개별 에이전트 실패가 전체 토론을 막지 않도록
                opinions.append(
                    AgentOpinion(
                        agent_name=agent.name,
                        signal=Signal.WATCH,
                        confidence=0.1,
                        rationale=f"평가 실패: {exc}",
                        risk_flags=[f"에이전트 오류: {exc}"],
                    )
                )
        return opinions

    # ── Phase 2: 교차 반박 ──────────────────────────────────────────────────

    def _cross_examine(self, opinions: list[AgentOpinion]) -> list[Rebuttal]:
        """상충하는 의견 쌍에 대해 반박을 생성한다.

        fin-advisor와 동일한 패턴: positive vs negative 신호 쌍.
        """
        rebuttals: list[Rebuttal] = []
        positive = [o for o in opinions if o.signal in POSITIVE_SIGNALS]
        negative = [o for o in opinions if o.signal in NEGATIVE_SIGNALS]

        # 낙관론 vs 비관론 교차 반박
        for bull in positive:
            for bear in negative:
                agent = self._get_agent(bull.agent_name)
                if agent:
                    r = agent.rebut(bull, bear)
                    if r:
                        rebuttals.append(r)
                agent2 = self._get_agent(bear.agent_name)
                if agent2:
                    r2 = agent2.rebut(bear, bull)
                    if r2:
                        rebuttals.append(r2)

        return rebuttals

    def _get_agent(self, name: str) -> StockAgent | None:
        return next((a for a in self.agents if a.name == name), None)

    # ── Phase 3: 투표 집계 ──────────────────────────────────────────────────

    def _tally_votes(self, opinions: list[AgentOpinion]) -> dict[str, int]:
        """신호별 득표수를 집계한다."""
        tally: dict[str, int] = Counter()
        for o in opinions:
            if o.signal in POSITIVE_SIGNALS:
                tally["positive"] += 1
            elif o.signal in NEGATIVE_SIGNALS:
                tally["negative"] += 1
            else:
                tally["neutral"] += 1
        return dict(tally)

    # ── Phase 4: 최종 신호 결정 ─────────────────────────────────────────────

    def _determine_signal(
        self, opinions: list[AgentOpinion], vote_tally: dict[str, int]
    ) -> Signal:
        """confidence 가중 투표로 최종 신호를 결정한다.

        fin-advisor moderator._determine_signal 패턴 계승.
        """
        weights: dict[Signal, float] = Counter()
        total_weight = 0.0

        for opinion in opinions:
            weights[opinion.signal] += opinion.confidence
            total_weight += opinion.confidence

        if total_weight == 0:
            return Signal.WATCH

        best_signal = max(weights, key=lambda s: weights[s])
        best_weight = weights[best_signal]

        # 확신이 약하면 WATCH로 수렴
        if best_weight / total_weight < 0.25:
            return Signal.WATCH

        return best_signal

    def _compute_confidence(
        self, opinions: list[AgentOpinion], final_signal: Signal
    ) -> float:
        """최종 신호에 동의하는 에이전트들의 평균 confidence."""
        agreeing = []
        for o in opinions:
            if (
                final_signal in POSITIVE_SIGNALS and o.signal in POSITIVE_SIGNALS
            ) or (
                final_signal in NEGATIVE_SIGNALS and o.signal in NEGATIVE_SIGNALS
            ) or o.signal == final_signal:
                agreeing.append(o.confidence)

        if not agreeing:
            return 0.3
        return sum(agreeing) / len(agreeing)

    def _classify_urgency(
        self,
        opinions: list[AgentOpinion],
        vote_tally: dict[str, int],
        final_signal: Signal,
    ) -> Urgency:
        """토론 결과의 긴급도를 분류한다.

        fin-advisor와 동일한 4단계 분류:
        - UNANIMOUS: 전원 동의
        - MAJORITY: 4+ 동의
        - SPLIT: 의견 분열
        - RED_FLAG: 리스크 에이전트 거부권
        """
        # RED_FLAG: 리스크 에이전트가 AVOID + confidence >= 0.8
        risk_opinion = next(
            (o for o in opinions if o.agent_name == "risk-analyst"), None
        )
        if (
            risk_opinion
            and risk_opinion.signal == Signal.AVOID
            and risk_opinion.confidence >= 0.8
            and final_signal in POSITIVE_SIGNALS
        ):
            return Urgency.RED_FLAG

        n = len(opinions)
        positive = vote_tally.get("positive", 0)
        negative = vote_tally.get("negative", 0)

        # UNANIMOUS: 모두 같은 방향
        if positive == n or negative == n:
            return Urgency.UNANIMOUS

        # MAJORITY: 2/3 이상
        if positive >= int(n * 0.66) + 1 or negative >= int(n * 0.66) + 1:
            return Urgency.MAJORITY

        return Urgency.SPLIT

    # ── Phase 5: 결과 포맷팅 ────────────────────────────────────────────────

    def _build_summary(
        self,
        opinions: list[AgentOpinion],
        final_signal: Signal,
        confidence: float,
        vote_tally: dict[str, int],
    ) -> str:
        signal_label = {
            Signal.STRONG_BUY: "강력 매수 추천",
            Signal.BUY: "매수 검토",
            Signal.WATCH: "관심종목 등록",
            Signal.PASS: "패스",
            Signal.AVOID: "회피",
        }.get(final_signal, final_signal.value)

        pos = vote_tally.get("positive", 0)
        neg = vote_tally.get("negative", 0)
        neu = vote_tally.get("neutral", 0)

        lines = [
            f"최종 의견: {signal_label} (신뢰도 {confidence*100:.0f}%)",
            f"투표: 긍정 {pos}표 / 중립 {neu}표 / 부정 {neg}표",
            "",
        ]

        for o in opinions:
            signal_emoji = {
                Signal.STRONG_BUY: "⬆⬆",
                Signal.BUY: "⬆",
                Signal.WATCH: "➡",
                Signal.PASS: "⬇",
                Signal.AVOID: "⬇⬇",
            }.get(o.signal, "?")
            lines.append(f"{signal_emoji} [{o.agent_name}] {o.rationale}")

        return "\n".join(lines)

    def _build_thesis(self, opinions: list[AgentOpinion], final_signal: Signal) -> str:
        """투자 thesis 문장을 조립한다."""
        strengths = []
        for o in opinions:
            if o.signal in POSITIVE_SIGNALS:
                strengths.extend(o.strengths[:1])

        if not strengths:
            return "투자 thesis 구성 불충분 — 추가 조사 권장"

        return " | ".join(strengths[:3])

    def _collect_risks(self, opinions: list[AgentOpinion]) -> list[str]:
        """모든 에이전트의 risk_flags를 모아 중복 제거 후 반환."""
        seen: set[str] = set()
        result: list[str] = []
        for o in opinions:
            for flag in o.risk_flags:
                if flag not in seen:
                    seen.add(flag)
                    result.append(flag)
        return result

    def _suggest_entry(
        self,
        context: StockAnalysisContext,
        opinions: list[AgentOpinion],
        final_signal: Signal,
    ) -> list[str]:
        """진입 조건 제안을 생성한다."""
        conditions: list[str] = []
        ind = {}
        if context.market_data:
            latest = context.market_data[-1]
            ind = {
                "rsi_14": latest.get("rsi_14"),
                "sma_50": latest.get("sma_50"),
                "macd": latest.get("macd"),
                "macd_signal": latest.get("macd_signal"),
                "close": latest.get("close"),
            }

        if final_signal in POSITIVE_SIGNALS:
            if ind.get("rsi_14") and ind["rsi_14"] > 60:
                conditions.append("RSI 50 이하 조정 후 재확인")
            if ind.get("close") and ind.get("sma_50"):
                if ind["close"] > ind["sma_50"] * 1.10:
                    conditions.append("SMA50 근접 조정 시 분할 매수")
            conditions.append("실적 발표 후 가이던스 확인")
        elif final_signal == Signal.WATCH:
            conditions.append("RSI 40 이하 진입 시 재평가")
            conditions.append("매출 성장 가속 신호 확인")

        return conditions if conditions else ["현재 조건으로 진입 가능"]


# ValuationAgent를 여기서 임포트 (순환참조 방지)
class ValuationAgentLazy(StockAgent):
    """ValuationAgent 래퍼 — 순환 임포트 없이 지연 로드."""

    name = "valuation-analyst"
    description = "밸류에이션 평가 (래퍼)"

    def __init__(self) -> None:
        from src.agents.valuation_agent import ValuationAgent
        self._inner = ValuationAgent()
        self.name = self._inner.name
        self.description = self._inner.description

    def evaluate(self, context: StockAnalysisContext) -> AgentOpinion:
        return self._inner.evaluate(context)
