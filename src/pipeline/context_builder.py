"""종목 분석 컨텍스트 빌더.

fin-advisor의 context_builder.py 패턴을 계승.
yfinance 데이터를 StockAnalysisContext로 조립한다.
"""

from __future__ import annotations

import logging
import math
import time

import pandas as pd
import yfinance as yf

from src.agents.models import StockAnalysisContext
from src.utils.config import SECTOR_PEER_MAP, PEER_FETCH_TIMEOUT

logger = logging.getLogger(__name__)


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
    raw_fundamentals = _extract_fundamentals(info)

    # 할루시네이션 방지: 펀더멘탈 데이터 검증
    from src.pipeline.data_validator import validate_fundamentals, assess_data_quality
    fundamentals, validation_warnings = validate_fundamentals(raw_fundamentals)

    # ── 재무 이력 ──────────────────────────────────────────────────────────
    financial_history = _fetch_financial_history(t)

    # ── 데이터 품질 평가 ───────────────────────────────────────────────────
    data_quality = assess_data_quality(fundamentals, market_data)
    data_quality.warnings.extend(validation_warnings)

    # ── 섹터 피어 비교 데이터 ──────────────────────────────────────────────
    sector_peers = _fetch_sector_peers(ticker, info)

    return StockAnalysisContext(
        ticker=ticker,
        company_name=company_name,
        market_data=market_data,
        fundamentals=fundamentals,
        financial_history=financial_history,
        data_quality=data_quality,
        sector_peers=sector_peers,
        # historical_multiples, sentiment_data, macro_snapshot
        # 는 추후 확장 (현재는 빈 리스트/dict)
    )


def _safe_float(val) -> float | None:
    """NaN-safe float 변환. NaN/None → None."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ── 피어 데이터 캐시 (모듈 레벨) ─────────────────────────────────────────────
# key: ticker, value: (timestamp, dict | None)
_peer_cache: dict[str, tuple[float, dict | None]] = {}
_PEER_CACHE_TTL = 3600  # 1시간


def _fetch_sector_peers(ticker: str, info: dict) -> list[dict]:
    """동종 업체 핵심 지표를 수집한다.

    1. info에서 sector를 읽어 SECTOR_PEER_MAP에서 대표 티커를 가져온다.
    2. 각 피어 티커에 대해 yfinance로 핵심 멀티플을 조회한다.
    3. 실패한 피어는 건너뛰고, 수집된 데이터만 반환한다.

    Returns:
        list[dict] — 각 dict는 pe, pb, ev_ebitda, gross_margin, roe, market_cap 키를 가짐.
    """
    sector = info.get("sector")
    if not sector:
        logger.debug("섹터 정보 없음 — 피어 비교 건너뜀")
        return []

    peer_tickers = SECTOR_PEER_MAP.get(sector, [])
    if not peer_tickers:
        logger.debug("섹터 '%s'에 대한 피어 매핑 없음", sector)
        return []

    # 분석 대상 자신은 제외
    peer_tickers = [p for p in peer_tickers if p.upper() != ticker.upper()]

    results = []
    for pticker in peer_tickers:
        try:
            peer_data = _fetch_single_peer(pticker)
            if peer_data is not None:
                results.append(peer_data)
        except Exception as exc:  # noqa: BLE001
            logger.debug("피어 %s 데이터 수집 실패: %s", pticker, exc)
            continue

    logger.info("섹터 '%s' 피어 %d/%d 수집 완료", sector, len(results), len(peer_tickers))
    return results


def _fetch_single_peer(ticker: str) -> dict | None:
    """단일 피어 티커의 핵심 지표를 조회한다 (캐시 활용)."""
    now = time.time()

    # 캐시 확인
    if ticker in _peer_cache:
        cached_time, cached_data = _peer_cache[ticker]
        if now - cached_time < _PEER_CACHE_TTL:
            return cached_data

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception:
        _peer_cache[ticker] = (now, None)
        return None

    pe = _safe_float(info.get("trailingPE")) or _safe_float(info.get("forwardPE"))
    pb = _safe_float(info.get("priceToBook"))
    ev_ebitda = _safe_float(info.get("enterpriseToEbitda"))
    gross_margin = _safe_float(info.get("grossMargins"))
    roe = _safe_float(info.get("returnOnEquity"))
    market_cap = _safe_float(info.get("marketCap"))

    # 최소한 하나의 유효한 지표가 있어야 의미 있음
    values = [pe, pb, ev_ebitda, gross_margin, roe, market_cap]
    if all(v is None for v in values):
        _peer_cache[ticker] = (now, None)
        return None

    data = {
        "ticker": ticker,
        "pe": pe,
        "pb": pb,
        "ev_ebitda": ev_ebitda,
        "gross_margin": gross_margin,
        "roe": roe,
        "market_cap": market_cap,
    }

    _peer_cache[ticker] = (now, data)
    return data


def _fetch_market_data(t: yf.Ticker, days: int) -> list[dict]:
    """OHLCV + 기술적 지표를 계산하여 반환한다.

    ta 라이브러리 사용 (RSI, MACD, SMA, Bollinger Bands).
    """
    try:
        import ta as ta_lib

        hist = t.history(period=f"{days}d", interval="1d")
        if hist.empty:
            return []

        # yfinance ≥ 0.2.36: 비미국 티커에서 MultiIndex 컬럼 반환 대응
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)

        # Close가 NaN인 행 제거
        hist = hist.dropna(subset=["Close"])
        if hist.empty:
            return []

        close = hist["Close"]

        # 각 지표를 개별 try/except로 감싸서 하나가 실패해도 나머지 유지
        rsi = None
        try:
            rsi = ta_lib.momentum.RSIIndicator(close=close, window=14).rsi()
        except Exception as exc:
            logger.debug("RSI 계산 실패: %s", exc)

        macd_line = macd_signal = macd_hist = None
        try:
            macd_ind = ta_lib.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
            macd_line = macd_ind.macd()
            macd_signal = macd_ind.macd_signal()
            macd_hist = macd_ind.macd_diff()
        except Exception as exc:
            logger.debug("MACD 계산 실패: %s", exc)

        sma20 = sma50 = sma200 = None
        try:
            sma20 = ta_lib.trend.SMAIndicator(close=close, window=20).sma_indicator()
            sma50 = ta_lib.trend.SMAIndicator(close=close, window=50).sma_indicator()
            sma200 = ta_lib.trend.SMAIndicator(close=close, window=200).sma_indicator()
        except Exception as exc:
            logger.debug("SMA 계산 실패: %s", exc)

        bb_upper = bb_mid = bb_lower = None
        try:
            bb = ta_lib.volatility.BollingerBands(close=close, window=20, window_dev=2)
            bb_upper = bb.bollinger_hband()
            bb_mid = bb.bollinger_mavg()
            bb_lower = bb.bollinger_lband()
        except Exception as exc:
            logger.debug("Bollinger Bands 계산 실패: %s", exc)

        def _v(series, i):
            if series is None:
                return None
            try:
                val = series.loc[i]
                return _safe_float(val)
            except Exception:
                return None

        records = []
        for date, row in hist.iterrows():
            idx = date
            records.append({
                "date": str(date.date()),
                "open": _safe_float(row.get("Open")),
                "high": _safe_float(row.get("High")),
                "low": _safe_float(row.get("Low")),
                "close": _safe_float(row.get("Close")),
                "volume": _safe_float(row.get("Volume")),
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

    except Exception as exc:  # noqa: BLE001
        logger.warning("시장 데이터 수집 실패 (%s): %s", t.ticker, exc)
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

    except Exception as exc:  # noqa: BLE001
        logger.warning("재무 이력 수집 실패: %s", exc)
        return []


def _get_row(df, col, possible_keys: list[str]):
    """DataFrame에서 여러 가능한 행 이름으로 값을 찾는다."""
    for key in possible_keys:
        if key in df.index:
            val = df.loc[key, col]
            result = _safe_float(val)
            if result is not None:
                return result
    return None
