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
    return StockAnalysisContext(**defaults)


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
        if risk_op and risk_op.signal == S.AVOID and risk_op.confidence >= 0.8:
            assert result.urgency == Urgency.RED_FLAG
