"""신호 결정 전략 레지스트리.

V1~V6 + 매크로 게이트 전략을 모두 등록하고,
매크로 레짐에 따라 자동 선택하거나 수동 지정할 수 있다.

Usage:
    # 자동 선택 (매크로 레짐 기반)
    strategy = get_strategy("auto", macro_regime="bear")

    # 수동 지정
    strategy = get_strategy("v3")

    # 전략 적용
    final_signal = strategy.apply(opinions, base_signal)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from src.agents.models import AgentOpinion, Signal, POSITIVE_SIGNALS, NEGATIVE_SIGNALS

logger = logging.getLogger(__name__)


# ── 전략 정의 ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StrategyParams:
    """전략별 파라미터."""
    name: str
    description: str
    # risk-analyst를 투표에서 제외하고 거부권 전용으로 할지
    risk_veto_only: bool = False
    # BUY 최소 긍정 투표 수 (risk 제외 5명 기준)
    min_positive_for_buy: int = 3
    # STRONG_BUY 최소 긍정 투표 수
    min_positive_for_strong_buy: int = 4
    # valuation PASS/AVOID → STRONG_BUY 차단 (conf 임계값, 0이면 비활성)
    val_block_sb_conf: float = 0.0
    # valuation AVOID → BUY 차단 (conf 임계값, 0이면 비활성)
    val_block_buy_conf: float = 0.0
    # growth STRONG_BUY이면 valuation BUY 차단 면제
    growth_sb_exempts_val: bool = False
    # growth STRONG_BUY이면 valuation SB 차단도 면제
    growth_sb_exempts_val_sb: bool = False
    # momentum PASS/AVOID → BUY 차단 (conf 임계값, 0이면 비활성)
    momentum_block_conf: float = 0.0
    # 매크로 게이트: bear 시 STRONG_BUY 차단
    bear_blocks_sb: bool = False
    # 매크로 게이트: bear 시 BUY → WATCH 하향
    bear_downgrades_buy: bool = False
    # 매크로 게이트: bear + growth SB이면 BUY 하향 면제
    bear_growth_sb_exempts_buy: bool = False


# ── 전략 카탈로그 ─────────────────────────────────────────────────────────────

STRATEGIES: dict[str, StrategyParams] = {
    "legacy": StrategyParams(
        name="legacy",
        description="기존 규칙 (가중 투표, 제한 없음)",
    ),
    "v1": StrategyParams(
        name="v1",
        description="엄격: 최소합의 + risk 거부권전용 + val 강차단(0.65) + mom 필터",
        risk_veto_only=True,
        val_block_sb_conf=0.50,
        val_block_buy_conf=0.65,
        momentum_block_conf=0.55,
    ),
    "v2": StrategyParams(
        name="v2",
        description="V1 + val 강차단 완화(0.75)",
        risk_veto_only=True,
        val_block_sb_conf=0.50,
        val_block_buy_conf=0.75,
        momentum_block_conf=0.55,
    ),
    "v3": StrategyParams(
        name="v3",
        description="V1 + growth SB이면 val BUY차단 면제",
        risk_veto_only=True,
        val_block_sb_conf=0.50,
        val_block_buy_conf=0.65,
        growth_sb_exempts_val=True,
        momentum_block_conf=0.55,
    ),
    "v4": StrategyParams(
        name="v4",
        description="V2 + V3 결합 (val 0.75 완화 + growth SB 면제)",
        risk_veto_only=True,
        val_block_sb_conf=0.50,
        val_block_buy_conf=0.75,
        growth_sb_exempts_val=True,
        momentum_block_conf=0.55,
    ),
    "v5": StrategyParams(
        name="v5",
        description="V4 + mom 필터 완화(0.60)",
        risk_veto_only=True,
        val_block_sb_conf=0.50,
        val_block_buy_conf=0.75,
        growth_sb_exempts_val=True,
        momentum_block_conf=0.60,
    ),
    "v6": StrategyParams(
        name="v6",
        description="V4 + growth SB이면 val SB차단도 면제",
        risk_veto_only=True,
        val_block_sb_conf=0.50,
        val_block_buy_conf=0.75,
        growth_sb_exempts_val=True,
        growth_sb_exempts_val_sb=True,
        momentum_block_conf=0.55,
    ),
    # ── 매크로 게이트 변형 (V3 기반) ──
    "v3-bear": StrategyParams(
        name="v3-bear",
        description="V3 + bear → SB차단 + BUY→WATCH(growth SB 면제)",
        risk_veto_only=True,
        val_block_sb_conf=0.50,
        val_block_buy_conf=0.65,
        growth_sb_exempts_val=True,
        momentum_block_conf=0.55,
        bear_blocks_sb=True,
        bear_downgrades_buy=True,
        bear_growth_sb_exempts_buy=True,
    ),
    "v3-defensive": StrategyParams(
        name="v3-defensive",
        description="V3 + bear → 전체 1단계 하향 (면제 없음)",
        risk_veto_only=True,
        val_block_sb_conf=0.50,
        val_block_buy_conf=0.65,
        growth_sb_exempts_val=True,
        momentum_block_conf=0.55,
        bear_blocks_sb=True,
        bear_downgrades_buy=True,
        bear_growth_sb_exempts_buy=False,
    ),
}


# ── 자동 선택 매핑 ────────────────────────────────────────────────────────────

REGIME_STRATEGY_MAP: dict[str, str] = {
    "bull": "v6",            # 상승장: 가장 관대한 전략
    "neutral": "v3",         # 보합: 기본 선별
    "bear": "v3-bear",       # 하락장: 매크로 게이트 추가
}


# ── 전략 적용 엔진 ────────────────────────────────────────────────────────────

def _get_agent_opinion(opinions: list[AgentOpinion], name: str) -> AgentOpinion | None:
    return next((o for o in opinions if o.agent_name == name), None)


def apply_strategy(
    params: StrategyParams,
    opinions: list[AgentOpinion],
    macro_regime: str = "neutral",
) -> tuple[Signal, str]:
    """전략 파라미터에 따라 최종 신호를 결정한다.

    Returns:
        (final_signal, strategy_note) — 적용된 전략과 사유
    """
    if params.name == "legacy":
        return _legacy_signal(opinions), "legacy 가중투표"

    risk = _get_agent_opinion(opinions, "risk-analyst")
    val = _get_agent_opinion(opinions, "valuation-analyst")
    mom = _get_agent_opinion(opinions, "momentum-analyst")
    growth = _get_agent_opinion(opinions, "growth-analyst")

    # 투표 대상 결정
    if params.risk_veto_only:
        voters = [o for o in opinions if o.agent_name != "risk-analyst"]
    else:
        voters = list(opinions)

    pos = sum(1 for o in voters if o.signal in POSITIVE_SIGNALS)
    neg = sum(1 for o in voters if o.signal in NEGATIVE_SIGNALS)

    notes: list[str] = [f"투표 {pos}/{len(voters)} 긍정"]

    # ── 합의 기반 신호 결정 ──
    if pos >= params.min_positive_for_strong_buy:
        sig = Signal.STRONG_BUY
    elif pos >= params.min_positive_for_buy:
        sig = Signal.BUY
    elif neg >= 3:
        sig = Signal.AVOID
    elif neg >= 2:
        sig = Signal.PASS
    else:
        sig = Signal.WATCH

    # ── risk 거부권 (투표 제외 모드에서만) ──
    if params.risk_veto_only and risk:
        if risk.signal == Signal.AVOID and risk.confidence >= 0.85 and sig in POSITIVE_SIGNALS:
            sig = Signal.WATCH
            notes.append("risk 하드거부")
        elif risk.signal == Signal.AVOID and risk.confidence >= 0.70 and sig == Signal.STRONG_BUY:
            sig = Signal.BUY
            notes.append("risk 소프트거부")

    # ── valuation 차단 ──
    growth_sb = growth and growth.signal == Signal.STRONG_BUY

    if params.val_block_sb_conf > 0 and val:
        if (val.signal in NEGATIVE_SIGNALS
                and val.confidence >= params.val_block_sb_conf
                and sig == Signal.STRONG_BUY):
            if not (params.growth_sb_exempts_val_sb and growth_sb):
                sig = Signal.BUY
                notes.append("val→SB차단")

    if params.val_block_buy_conf > 0 and val:
        if (val.signal == Signal.AVOID
                and val.confidence >= params.val_block_buy_conf
                and sig == Signal.BUY):
            if not (params.growth_sb_exempts_val and growth_sb):
                sig = Signal.WATCH
                notes.append("val→BUY차단")

    # ── momentum 차단 ──
    if params.momentum_block_conf > 0 and mom:
        if (mom.signal in NEGATIVE_SIGNALS
                and mom.confidence >= params.momentum_block_conf
                and sig in POSITIVE_SIGNALS):
            sig = Signal.WATCH
            notes.append("momentum 하락")

    # ── 매크로 게이트 ──
    if macro_regime == "bear":
        if params.bear_blocks_sb and sig == Signal.STRONG_BUY:
            sig = Signal.BUY
            notes.append("bear→SB차단")
        if params.bear_downgrades_buy and sig == Signal.BUY:
            if not (params.bear_growth_sb_exempts_buy and growth_sb):
                sig = Signal.WATCH
                notes.append("bear→BUY↓")

    return sig, f"[{params.name}] " + " | ".join(notes)


def _legacy_signal(opinions: list[AgentOpinion]) -> Signal:
    """기존 가중 투표 로직 (호환용)."""
    signal_confs: dict[Signal, list[float]] = {}
    total = 0.0
    for o in opinions:
        signal_confs.setdefault(o.signal, []).append(o.confidence)
        total += o.confidence
    if total == 0:
        return Signal.WATCH
    effective = {}
    for sig, confs in signal_confs.items():
        effective[sig] = sum(confs) * (1 + 0.1 * len(confs))
    best = max(effective, key=lambda s: effective[s])
    if sum(signal_confs[best]) / total < 0.25:
        return Signal.WATCH
    return best


# ── 공개 API ──────────────────────────────────────────────────────────────────

def get_strategy(name: str = "auto", macro_regime: str = "neutral") -> StrategyParams:
    """전략을 이름 또는 자동으로 선택한다."""
    if name == "auto":
        selected = REGIME_STRATEGY_MAP.get(macro_regime, "v3")
        logger.info("매크로 레짐 '%s' → 전략 '%s' 자동 선택", macro_regime, selected)
        return STRATEGIES[selected]
    if name not in STRATEGIES:
        logger.warning("알 수 없는 전략 '%s' → v3 폴백", name)
        return STRATEGIES["v3"]
    return STRATEGIES[name]


def list_strategies() -> list[dict[str, str]]:
    """등록된 전략 목록을 반환한다."""
    return [{"name": s.name, "description": s.description} for s in STRATEGIES.values()]
