"""Data models for the stock exploration multi-agent system.

fin-advisor의 debate/models.py 패턴을 계승.
포트폴리오 관리 → 신규 종목 탐색에 맞게 확장.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Signal(str, Enum):
    STRONG_BUY = "strong_buy"   # 강력 매수 추천 (탐험 → 편입 후보 1순위)
    BUY = "buy"                  # 매수 검토
    WATCH = "watch"              # 관심종목 등록 (진입 조건 대기)
    PASS = "pass"                # 현재 기준 패스
    AVOID = "avoid"              # 회피 (명확한 결격 사유)


class Urgency(str, Enum):
    UNANIMOUS = "unanimous"     # 전원 동의 → 즉시 관심종목 등록
    MAJORITY = "majority"       # 다수 동의 → 추가 검토 권장
    SPLIT = "split"             # 의견 분열 → 사용자 판단 요청
    RED_FLAG = "red_flag"       # 리스크 에이전트 거부권 행사


# Signal 그룹핑
POSITIVE_SIGNALS = {Signal.STRONG_BUY, Signal.BUY}
NEUTRAL_SIGNALS = {Signal.WATCH}
NEGATIVE_SIGNALS = {Signal.PASS, Signal.AVOID}


@dataclass
class StockAnalysisContext:
    """에이전트들에게 제공되는 종목 분석 컨텍스트.

    fin-advisor의 DebateContext 패턴을 계승하되
    신규 종목 탐색에 특화된 필드로 구성.
    """

    ticker: str
    company_name: str = ""

    # 시장 데이터 (fin-advisor collection 재사용)
    market_data: list[dict] = field(default_factory=list)       # 90일 OHLCV + 기술지표
    fundamentals: dict = field(default_factory=dict)            # P/E, P/B, ROE, FCF 등

    # 재무 이력 (추가)
    financial_history: list[dict] = field(default_factory=list) # 연간 매출/이익/현금흐름
    segment_data: list[dict] = field(default_factory=list)      # 사업부문별 매출 (있는 경우)

    # 밸류에이션 비교
    sector_peers: list[dict] = field(default_factory=list)      # 동종 기업 멀티플
    historical_multiples: dict = field(default_factory=dict)    # 과거 P/E 등 밴드

    # 뉴스 & 감성 (fin-advisor collection 재사용)
    sentiment_data: list[dict] = field(default_factory=list)    # 최근 뉴스 + 감성점수

    # 매크로 컨텍스트 (fin-advisor FRED 재사용)
    macro_snapshot: list[dict] = field(default_factory=list)    # FRED 지표 스냅샷


@dataclass
class AgentOpinion:
    """개별 에이전트의 종목 평가 의견.

    fin-advisor의 StrategyOpinion과 동일한 구조.
    """

    agent_name: str
    signal: Signal
    confidence: float           # 0.0 ~ 1.0
    rationale: str              # 2-3줄 근거
    key_metrics: dict = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)


@dataclass
class Rebuttal:
    """상충하는 의견에 대한 반박."""

    agent_name: str
    target_agent: str
    argument: str


@dataclass
class ExplorationResult:
    """종목 탐험 최종 결과.

    fin-advisor의 DebateResult 패턴을 계승.
    """

    ticker: str
    company_name: str
    opinions: list[AgentOpinion]
    rebuttals: list[Rebuttal] = field(default_factory=list)
    vote_tally: dict[str, int] = field(default_factory=dict)
    final_signal: Signal = Signal.WATCH
    final_confidence: float = 0.0
    urgency: Urgency = Urgency.SPLIT
    summary: str = ""
    investment_thesis: str = ""
    key_risks: list[str] = field(default_factory=list)
    entry_conditions: list[str] = field(default_factory=list)
    timestamp: str = ""
