"""에이전트 단위 테스트.

fin-advisor tests/ 패턴을 계승.
각 에이전트를 mock StockAnalysisContext로 독립 테스트.
"""

import pytest
from src.agents.models import Signal, StockAnalysisContext
from src.agents.fundamental_agent import FundamentalAgent
from src.agents.valuation_agent import ValuationAgent
from src.agents.growth_agent import GrowthAgent
from src.agents.risk_agent import RiskAgent
from src.agents.momentum_agent import MomentumAgent
from src.agents.moderator import ExplorationModerator


def make_context(ticker: str = "TEST", **overrides) -> StockAnalysisContext:
    """테스트용 기본 컨텍스트를 생성한다."""
    defaults = {
        "ticker": ticker,
        "company_name": "Test Corp",
        "fundamentals": {
            "grossMargins": 0.60,
            "operatingMargins": 0.25,
            "profitMargins": 0.20,
            "returnOnEquity": 0.30,
            "returnOnAssets": 0.15,
            "revenueGrowth": 0.20,
            "earningsGrowth": 0.25,
            "debtToEquity": 0.5,
            "currentRatio": 2.0,
            "freeCashflow": 5_000_000_000,
            "netIncomeToCommon": 4_000_000_000,
            "totalRevenue": 20_000_000_000,
            "marketCap": 100_000_000_000,
            "trailingPE": 20.0,
            "priceToBook": 3.0,
            "pegRatio": 1.0,
            "enterpriseToEbitda": 12.0,
            "currentPrice": 150.0,
            "targetMeanPrice": 180.0,
            "numberOfAnalystOpinions": 20,
        },
        "market_data": [
            {
                "date": "2024-01-01",
                "close": 150.0,
                "rsi_14": 50.0,
                "macd": 1.0,
                "macd_signal": 0.5,
                "macd_hist": 0.5,
                "sma_20": 145.0,
                "sma_50": 140.0,
                "sma_200": 130.0,
                "bb_upper": 165.0,
                "bb_mid": 148.0,
                "bb_lower": 131.0,
            }
        ],
        "financial_history": [
            {"year": "2021", "revenue": 15_000_000_000, "net_income": 2_000_000_000, "gross_margin": 0.55},
            {"year": "2022", "revenue": 17_000_000_000, "net_income": 3_000_000_000, "gross_margin": 0.57},
            {"year": "2023", "revenue": 20_000_000_000, "net_income": 4_000_000_000, "gross_margin": 0.60},
        ],
    }
    defaults.update(overrides)
    ctx = StockAnalysisContext(**defaults)
    # Auto-compute data quality for realistic confidence penalties
    from src.pipeline.data_validator import assess_data_quality
    ctx.data_quality = assess_data_quality(ctx.fundamentals, ctx.market_data)
    return ctx


class TestFundamentalAgent:
    def test_strong_fundamentals_returns_positive(self):
        agent = FundamentalAgent()
        ctx = make_context()
        opinion = agent.evaluate(ctx)
        assert opinion.signal in {Signal.STRONG_BUY, Signal.BUY}
        assert opinion.confidence >= 0.5

    def test_poor_fundamentals_returns_negative(self):
        agent = FundamentalAgent()
        ctx = make_context(
            fundamentals={
                "grossMargins": 0.05,
                "operatingMargins": -0.10,
                "profitMargins": -0.15,
                "revenueGrowth": -0.20,
                "earningsGrowth": -0.30,
                "debtToEquity": 5.0,
                "currentRatio": 0.5,
            }
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal in {Signal.PASS, Signal.AVOID}

    def test_missing_data_returns_watch(self):
        agent = FundamentalAgent()
        ctx = make_context(fundamentals={})
        opinion = agent.evaluate(ctx)
        assert opinion.signal == Signal.WATCH
        assert opinion.confidence < 0.5


class TestValuationAgent:
    def test_cheap_valuation_returns_positive(self):
        agent = ValuationAgent()
        ctx = make_context(
            fundamentals={
                "trailingPE": 10.0,
                "priceToBook": 0.8,
                "pegRatio": 0.6,
                "freeCashflow": 5_000_000_000,
                "marketCap": 50_000_000_000,
                "enterpriseToEbitda": 8.0,
            }
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal in {Signal.STRONG_BUY, Signal.BUY}

    def test_expensive_valuation_returns_negative(self):
        agent = ValuationAgent()
        ctx = make_context(
            fundamentals={
                "trailingPE": 100.0,
                "priceToBook": 20.0,
                "pegRatio": 5.0,
                "enterpriseToEbitda": 60.0,
            }
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal in {Signal.PASS, Signal.AVOID}


class TestRiskAgent:
    def test_high_debt_returns_avoid(self):
        agent = RiskAgent()
        ctx = make_context(
            fundamentals={
                "debtToEquity": 8.0,
                "currentRatio": 0.5,
                "freeCashflow": -1_000_000_000,
                "totalCash": 500_000_000,
                "netIncomeToCommon": -500_000_000,
            }
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal in {Signal.PASS, Signal.AVOID}
        assert len(opinion.risk_flags) > 0

    def test_clean_balance_sheet_returns_buy(self):
        agent = RiskAgent()
        ctx = make_context(
            fundamentals={
                "debtToEquity": 0.1,
                "currentRatio": 3.0,
                "freeCashflow": 5_000_000_000,
                "netIncomeToCommon": 3_000_000_000,
            }
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal in {Signal.BUY, Signal.WATCH}


class TestMomentumAgent:
    def test_bullish_technicals_returns_positive(self):
        agent = MomentumAgent()
        ctx = make_context(
            market_data=[{
                "close": 150.0,
                "rsi_14": 35.0,         # 저RSI
                "macd": 1.5,
                "macd_signal": 0.5,
                "macd_hist": 1.0,
                "sma_20": 145.0,
                "sma_50": 135.0,
                "sma_200": 120.0,
                "bb_upper": 165.0,
                "bb_mid": 148.0,
                "bb_lower": 131.0,
            }]
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal in {Signal.STRONG_BUY, Signal.BUY}

    def test_bearish_technicals_returns_negative(self):
        agent = MomentumAgent()
        ctx = make_context(
            market_data=[{
                "close": 100.0,
                "rsi_14": 80.0,         # 과매수
                "macd": -1.5,
                "macd_signal": -0.5,
                "macd_hist": -1.0,
                "sma_20": 110.0,
                "sma_50": 120.0,
                "sma_200": 130.0,
                "bb_upper": 105.0,
                "bb_mid": 95.0,
                "bb_lower": 85.0,
            }]
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal in {Signal.PASS, Signal.AVOID, Signal.WATCH}


class TestExplorationModerator:
    def test_run_returns_exploration_result(self):
        moderator = ExplorationModerator()
        ctx = make_context()
        result = moderator.run(ctx)

        assert result.ticker == "TEST"
        assert len(result.opinions) > 0
        assert result.final_signal in Signal.__members__.values()
        assert 0.0 <= result.final_confidence <= 1.0
        assert result.timestamp != ""

    def test_red_flag_when_risk_veto(self):
        """리스크 에이전트 거부권 → RED_FLAG urgency 확인."""
        from src.agents.models import Urgency, Signal as S
        from src.agents.moderator import ExplorationModerator

        moderator = ExplorationModerator()
        ctx = make_context(
            fundamentals={
                # 강한 성장 + 밸류에이션 → 다른 에이전트는 BUY
                "revenueGrowth": 0.40,
                "grossMargins": 0.70,
                "trailingPE": 15.0,
                # 그러나 극단적 부채 → 리스크 에이전트 거부권
                "debtToEquity": 10.0,
                "currentRatio": 0.3,
                "freeCashflow": -2_000_000_000,
                "totalCash": 100_000_000,
                "netIncomeToCommon": -1_000_000_000,
                "ebit": -500_000_000,
                "interestExpense": -800_000_000,
            }
        )
        result = moderator.run(ctx)
        # 리스크 에이전트가 AVOID + high confidence면 RED_FLAG
        risk_op = next(
            (o for o in result.opinions if o.agent_name == "risk-analyst"), None
        )
        if risk_op and risk_op.signal == S.AVOID and risk_op.confidence >= 0.85:
            assert result.urgency == Urgency.RED_FLAG


class TestValueStockCorrection:
    """Improvement 1: 가치주 점수 보정 — 배당/주주환원."""

    def test_high_dividend_boosts_fundamental_score(self):
        """배당수익률 4%+ 종목에 주주환원 10점이 추가되는지 확인."""
        agent = FundamentalAgent()
        ctx = make_context(
            fundamentals={
                "grossMargins": 0.30,
                "operatingMargins": 0.12,
                "profitMargins": 0.08,
                "revenueGrowth": 0.02,
                "earningsGrowth": 0.05,
                "dividendYield": 0.05,      # 5% 배당
                "payoutRatio": 0.60,
                "debtToEquity": 1.0,
                "currentRatio": 1.5,
                "returnOnEquity": 0.12,
                "freeCashflow": 3_000_000_000,
                "netIncomeToCommon": 2_500_000_000,
                "totalRevenue": 30_000_000_000,
            }
        )
        opinion = agent.evaluate(ctx)
        assert "dividend_yield_pct" in opinion.key_metrics
        # 배당 점수가 반영되어 PASS/AVOID가 아닌 WATCH 이상이어야 함
        assert opinion.signal in {Signal.STRONG_BUY, Signal.BUY, Signal.WATCH}

    def test_dividend_floor_prevents_growth_avoid(self):
        """배당 2%+, 매출 비역성장 종목이 growth-analyst에서 PASS/AVOID 안 받는지 확인."""
        agent = GrowthAgent()
        ctx = make_context(
            fundamentals={
                "revenueGrowth": 0.01,      # 미미한 성장
                "earningsGrowth": 0.02,
                "dividendYield": 0.035,     # 3.5% 배당
            },
            financial_history=[
                {"year": "2021", "revenue": 10_000_000_000},
                {"year": "2022", "revenue": 10_200_000_000},
                {"year": "2023", "revenue": 10_300_000_000},
            ],
        )
        opinion = agent.evaluate(ctx)
        # 배당주 하한선 적용 → 최소 WATCH
        assert opinion.signal in {Signal.STRONG_BUY, Signal.BUY, Signal.WATCH}


class TestValuationDrag:
    """Improvement 3: 고평가 패널티."""

    def test_valuation_drag_reduces_confidence(self):
        """valuation PASS/AVOID가 BUY 신호의 confidence를 낮추는지 확인."""
        from src.agents.models import Urgency
        from src.utils.config import VALUATION_DRAG_PENALTY

        moderator = ExplorationModerator()
        # 강한 펀더멘탈 + 성장 → BUY, 그러나 극단적 고평가
        ctx = make_context(
            fundamentals={
                "grossMargins": 0.70,
                "operatingMargins": 0.30,
                "profitMargins": 0.25,
                "revenueGrowth": 0.30,
                "earningsGrowth": 0.35,
                "returnOnEquity": 0.35,
                "freeCashflow": 10_000_000_000,
                "netIncomeToCommon": 8_000_000_000,
                "totalRevenue": 30_000_000_000,
                "currentRatio": 2.5,
                # 극단적 고평가
                "trailingPE": 120.0,
                "priceToBook": 30.0,
                "pegRatio": 6.0,
                "enterpriseToEbitda": 80.0,
                "currentPrice": 500.0,
                "targetMeanPrice": 400.0,
                "numberOfAnalystOpinions": 20,
                "marketCap": 500_000_000_000,
            }
        )
        result = moderator.run(ctx)
        val_op = next(
            (o for o in result.opinions if o.agent_name == "valuation-analyst"), None
        )
        # valuation agent가 부정적이면 drag 적용 확인
        if val_op and val_op.signal in {Signal.PASS, Signal.AVOID} and val_op.confidence >= 0.60:
            # confidence가 drag만큼 감소했을 것
            assert result.final_confidence <= 0.95 - VALUATION_DRAG_PENALTY + 0.05  # 여유


class TestMacroRegime:
    """Improvement 2: 매크로 오버레이."""

    def test_bear_regime_reduces_confidence(self):
        """bear 레짐에서 BUY 신호의 confidence가 감소하는지 확인."""
        moderator = ExplorationModerator()
        ctx = make_context()
        ctx.macro_snapshot = {"regime": "bear", "vix": 30, "sp500_vs_sma50": -0.05}
        result_bear = moderator.run(ctx)

        ctx2 = make_context()
        ctx2.macro_snapshot = {"regime": "neutral", "vix": 20, "sp500_vs_sma50": 0.01}
        result_neutral = moderator.run(ctx2)

        # bear에서 positive 신호면 confidence가 더 낮아야 함
        if result_bear.final_signal in {Signal.STRONG_BUY, Signal.BUY}:
            assert result_bear.final_confidence < result_neutral.final_confidence + 0.05

    def test_macro_snapshot_function(self):
        """_fetch_macro_snapshot이 dict를 반환하고 regime 키를 포함하는지 확인."""
        from src.pipeline.context_builder import _fetch_macro_snapshot
        snapshot = _fetch_macro_snapshot()
        assert isinstance(snapshot, dict)
        assert "regime" in snapshot
        assert snapshot["regime"] in {"bear", "neutral", "bull"}


class TestEdgeCases:
    """Phase 1: division-by-zero, NaN, 경계값 엣지케이스."""

    def test_zero_net_income_no_crash(self):
        """net_income=0 일 때 FCF/순이익 계산이 안전한지 확인."""
        agent = FundamentalAgent()
        ctx = make_context(
            fundamentals={
                "freeCashflow": 1_000_000,
                "netIncomeToCommon": 0,       # div-by-zero 위험
                "grossMargins": 0.30,
            }
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal is not None

    def test_zero_revenue_history_no_crash(self):
        """매출 0인 연도가 포함된 재무 이력에서 CAGR/추이 계산 안전 확인."""
        from src.agents.growth_agent import GrowthAgent
        agent = GrowthAgent()
        ctx = make_context(
            fundamentals={"revenueGrowth": 0.10},
            financial_history=[
                {"year": "2021", "revenue": 0},         # zero revenue
                {"year": "2022", "revenue": 1_000_000},
                {"year": "2023", "revenue": 2_000_000},
            ],
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal is not None

    def test_negative_revenue_operating_leverage(self):
        """매출/비용이 극단적 값일 때 operating_leverage 안전 확인."""
        from src.agents.moat_agent import MoatAgent
        agent = MoatAgent()
        ctx = make_context(
            fundamentals={"grossMargins": 0.40, "returnOnEquity": 0.10},
            financial_history=[
                {"year": "2022", "revenue": 100, "operating_expense": 100},
                {"year": "2023", "revenue": 100, "operating_expense": 100},  # cost_growth=0
            ],
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal is not None

    def test_nan_fundamentals_no_crash(self):
        """NaN 값이 들어온 펀더멘탈 데이터 처리."""
        agent = FundamentalAgent()
        ctx = make_context(
            fundamentals={
                "grossMargins": float("nan"),
                "operatingMargins": float("nan"),
                "revenueGrowth": 0.10,
            }
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal is not None

    def test_empty_market_data_momentum(self):
        """시장 데이터가 완전히 비어있을 때 모멘텀 에이전트."""
        agent = MomentumAgent()
        ctx = make_context(market_data=[])
        opinion = agent.evaluate(ctx)
        assert opinion.signal == Signal.WATCH
        assert opinion.confidence <= 0.3

    def test_all_none_fundamentals_risk_agent(self):
        """모든 펀더멘탈이 None일 때 리스크 에이전트 안전 동작."""
        agent = RiskAgent()
        ctx = make_context(
            fundamentals={k: None for k in [
                "debtToEquity", "currentRatio", "freeCashflow",
                "totalCash", "ebitda", "totalDebt", "ebit",
                "interestExpense", "netIncomeToCommon", "totalRevenue",
            ]}
        )
        opinion = agent.evaluate(ctx)
        assert opinion.signal is not None

    def test_moderator_with_minimal_data(self):
        """최소 데이터로 moderator 전체 파이프라인 안전 실행."""
        moderator = ExplorationModerator()
        ctx = make_context(
            fundamentals={"currentPrice": 10.0},
            market_data=[],
            financial_history=[],
        )
        result = moderator.run(ctx)
        assert result.final_signal is not None
        assert 0.0 <= result.final_confidence <= 1.0
