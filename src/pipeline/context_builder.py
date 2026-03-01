"""종목 분석 컨텍스트 빌더.

fin-advisor의 context_builder.py 패턴을 계승.
yfinance 데이터를 StockAnalysisContext로 조립한다.
"""

from __future__ import annotations

import yfinance as yf

from src.agents.models import StockAnalysisContext


def build_context(ticker: str, lookback_days: int = 90) -> StockAnalysisContext:
    """yfinance로 데이터를 수집하여 StockAnalysisContext를 생성한다.

    Args:
        ticker: 종목 심볼 (예: "AAPL", "005930.KS")
        lookback_days: 시장 데이터 조회 기간 (기본 90일)

    Returns:
        에이전트들이 사용할 StockAnalysisContext
    """
    t = yf.Ticker(ticker)
    info = t.info or {}

    company_name = (
        info.get("longName")
        or info.get("shortName")
        or ticker
    )

    # ── 시장 데이터 (OHLCV + 기술지표) ──────────────────────────────────────
    market_data = _fetch_market_data(t, lookback_days)

    # ── 펀더멘탈 ─────────────────────────────────────────────────────────────
    fundamentals = _extract_fundamentals(info)

    # ── 재무 이력 ──────────────────────────────────────────────────────────
    financial_history = _fetch_financial_history(t)

    return StockAnalysisContext(
        ticker=ticker,
        company_name=company_name,
        market_data=market_data,
        fundamentals=fundamentals,
        financial_history=financial_history,
        # sector_peers, historical_multiples, sentiment_data, macro_snapshot
        # 는 추후 확장 (현재는 빈 리스트/dict)
    )


def _fetch_market_data(t: yf.Ticker, days: int) -> list[dict]:
    """OHLCV + 기술적 지표를 계산하여 반환한다.

    ta 라이브러리 사용 (RSI, MACD, SMA, Bollinger Bands).
    """
    try:
        import ta as ta_lib

        hist = t.history(period=f"{days}d", interval="1d")
        if hist.empty:
            return []

        close = hist["Close"]

        # RSI
        rsi = ta_lib.momentum.RSIIndicator(close=close, window=14).rsi()

        # MACD
        macd_ind = ta_lib.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
        macd_line = macd_ind.macd()
        macd_signal = macd_ind.macd_signal()
        macd_hist = macd_ind.macd_diff()

        # SMA
        sma20 = ta_lib.trend.SMAIndicator(close=close, window=20).sma_indicator()
        sma50 = ta_lib.trend.SMAIndicator(close=close, window=50).sma_indicator()
        sma200 = ta_lib.trend.SMAIndicator(close=close, window=200).sma_indicator()

        # Bollinger Bands
        bb = ta_lib.volatility.BollingerBands(close=close, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband()
        bb_mid = bb.bollinger_mavg()
        bb_lower = bb.bollinger_lband()

        records = []
        for date, row in hist.iterrows():
            idx = date
            def _v(series, i):
                try:
                    val = series.loc[i]
                    return None if str(val) == "nan" else float(val)
                except Exception:
                    return None

            records.append({
                "date": str(date.date()),
                "open": float(row["Open"]) if row.get("Open") is not None else None,
                "high": float(row["High"]) if row.get("High") is not None else None,
                "low": float(row["Low"]) if row.get("Low") is not None else None,
                "close": float(row["Close"]) if row.get("Close") is not None else None,
                "volume": float(row["Volume"]) if row.get("Volume") is not None else None,
                "rsi_14": _v(rsi, idx),
                "macd": _v(macd_line, idx),
                "macd_signal": _v(macd_signal, idx),
                "macd_hist": _v(macd_hist, idx),
                "sma_20": _v(sma20, idx),
                "sma_50": _v(sma50, idx),
                "sma_200": _v(sma200, idx),
                "bb_upper": _v(bb_upper, idx),
                "bb_mid": _v(bb_mid, idx),
                "bb_lower": _v(bb_lower, idx),
            })
        return records

    except Exception:  # noqa: BLE001
        return []


def _extract_fundamentals(info: dict) -> dict:
    """yfinance info dict에서 핵심 펀더멘탈 지표를 추출한다.

    fin-advisor context_builder.py의 fundamentals 추출과 동일 패턴.
    """
    keys = [
        # 밸류에이션
        "trailingPE", "forwardPE", "priceToBook", "pegRatio",
        "enterpriseToEbitda", "enterpriseToRevenue",
        # 수익성
        "grossMargins", "operatingMargins", "profitMargins",
        "returnOnEquity", "returnOnAssets",
        # 성장
        "revenueGrowth", "earningsGrowth",
        # 재무 건전성
        "debtToEquity", "currentRatio", "quickRatio",
        # 현금흐름
        "freeCashflow", "operatingCashflow", "totalCash",
        # 규모
        "marketCap", "totalRevenue", "netIncomeToCommon",
        "enterpriseValue", "ebitda", "ebit",
        # 비용 구조
        "researchAndDevelopment", "interestExpense",
        # 애널리스트
        "targetMeanPrice", "targetHighPrice", "targetLowPrice",
        "numberOfAnalystOpinions",
        # 가격
        "currentPrice", "regularMarketPrice",
        # 부채 (Net Debt 계산용)
        "totalDebt",
        # 기타
        "sector", "industry", "country",
        "dividendYield", "payoutRatio",
    ]
    return {k: info.get(k) for k in keys}


def _fetch_financial_history(t: yf.Ticker) -> list[dict]:
    """연간 재무제표 이력을 추출한다 (최대 5년)."""
    try:
        income = t.financials  # 연간 손익계산서
        cashflow = t.cashflow  # 연간 현금흐름표

        if income is None or income.empty:
            return []

        records = []
        for col in income.columns[:5]:  # 최근 5년
            year = str(col.year) if hasattr(col, "year") else str(col)
            revenue = _get_row(income, col, ["Total Revenue", "totalRevenue"])
            gross_profit = _get_row(income, col, ["Gross Profit", "grossProfit"])
            operating_income = _get_row(income, col, ["Operating Income", "operatingIncome", "EBIT"])
            net_income = _get_row(income, col, ["Net Income", "netIncome"])
            op_expense = _get_row(income, col, ["Operating Expense", "totalOperatingExpenses"])

            fcf = None
            if cashflow is not None and not cashflow.empty and col in cashflow.columns:
                op_cf = _get_row(cashflow, col, ["Operating Cash Flow", "operatingCashflow"])
                capex = _get_row(cashflow, col, ["Capital Expenditure", "capitalExpenditure"])
                if op_cf is not None and capex is not None:
                    fcf = op_cf + capex  # capex는 음수로 기록됨

            gross_margin = (gross_profit / revenue) if (revenue and gross_profit) else None

            records.append({
                "year": year,
                "revenue": revenue,
                "gross_profit": gross_profit,
                "gross_margin": gross_margin,
                "operating_income": operating_income,
                "net_income": net_income,
                "operating_expense": op_expense,
                "fcf": fcf,
            })

        return list(reversed(records))  # 오래된 것 → 최신 순

    except Exception:  # noqa: BLE001
        return []


def _get_row(df, col, possible_keys: list[str]):
    """DataFrame에서 여러 가능한 행 이름으로 값을 찾는다."""
    for key in possible_keys:
        if key in df.index:
            val = df.loc[key, col]
            try:
                if val is not None and str(val) != "nan":
                    return float(val)
            except (TypeError, ValueError):
                pass
    return None
