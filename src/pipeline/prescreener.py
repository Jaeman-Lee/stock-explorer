"""사전 스크리닝 모듈.

전체 유니버스(500+종목)를 빠르게 점수화하여
6에이전트 풀 분석 대상 상위 N종목을 선별한다.

점수 기준 (10점 만점):
  RSI 35~55 구간      +2  (진입 가능 구간)
  현재가 > SMA50      +1  (단기 상승세)
  현재가 < SMA200     +1  (회복 후보)
  애널리스트 목표가 10%↑  +2
  매출 성장 > 10% YoY +2
  일평균 거래대금 $50M↑  +1
  시총 > $5B          +1  (기본 조건 충족)

방산 쿼터: defense_min개는 점수 무관하게 보장
"""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

# 방산 산업 분류 (yfinance industry 필드)
DEFENSE_INDUSTRIES = {"Aerospace & Defense"}

# 방산 티커 명시 (yfinance 분류가 불명확한 유럽 종목 포함)
DEFENSE_TICKERS = {
    # 미국
    "LMT", "RTX", "NOC", "GD", "LHX", "BA", "HII", "LDOS", "SAIC",
    # 유럽
    "RHM.DE",  # Rheinmetall
    "MTX.DE",  # MTU Aero Engines
    "BA.L",    # BAE Systems
    "HO.PA",   # Thales
    "SAF.PA",  # Safran
    "AIR.DE",  # Airbus
    "AIR.PA",  # Airbus (Paris)
    "LDO.MI",  # Leonardo
    "HAG.DE",  # Hensoldt
}

MIN_MARKET_CAP = 5_000_000_000   # $5B
MIN_DAILY_TURNOVER = 50_000_000  # $50M


def score_ticker(ticker: str) -> tuple[float, bool]:
    """단일 종목 사전 점수를 계산한다.

    Returns:
        (score, is_defense) 튜플
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # 방산 여부
        industry = info.get("industry", "")
        is_defense = (industry in DEFENSE_INDUSTRIES) or (ticker in DEFENSE_TICKERS)

        # 시총 기본 조건
        market_cap = info.get("marketCap") or 0
        if market_cap < MIN_MARKET_CAP:
            return (0.5 if is_defense else 0.0), is_defense

        score = 1.0  # 시총 조건 통과 +1

        # 가격 히스토리
        hist = t.history(period="90d", interval="1d")
        if hist.empty or len(hist) < 20:
            return score, is_defense

        close = hist["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()
        current = float(close.iloc[-1])

        # RSI (35~55 구간: +2)
        if len(close) >= 15:
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
            avg_loss = float(loss.iloc[-1])
            avg_gain = float(gain.iloc[-1])
            if avg_loss > 0:
                rsi = 100 - 100 / (1 + avg_gain / avg_loss)
                if 35 <= rsi <= 55:
                    score += 2

        # SMA50 위 (단기 상승세): +1
        if len(close) >= 50:
            sma50 = float(close.rolling(50).mean().iloc[-1])
            if current > sma50:
                score += 1

        # SMA200 아래 (회복 후보): +1
        if len(close) >= 200:
            sma200 = float(close.rolling(200).mean().iloc[-1])
            if current < sma200:
                score += 1

        # 애널리스트 목표가 10%↑: +2
        target = info.get("targetMeanPrice")
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        if target and current_price and current_price > 0:
            if target >= current_price * 1.10:
                score += 2

        # 매출 성장 > 10% YoY: +2
        rev_growth = info.get("revenueGrowth")
        if rev_growth and rev_growth > 0.10:
            score += 2

        # 일평균 거래대금 > $50M: +1
        avg_vol = info.get("averageVolume") or info.get("averageDailyVolume10Day") or 0
        price_ref = current_price or current
        if price_ref and avg_vol * price_ref >= MIN_DAILY_TURNOVER:
            score += 1

        return score, is_defense

    except Exception as e:
        log.debug(f"[{ticker}] 스크리닝 오류: {e}")
        return 0.0, ticker in DEFENSE_TICKERS


def prescreen(
    tickers: list[str],
    top_n: int = 30,
    defense_min: int = 5,
) -> list[str]:
    """전체 유니버스를 점수화하여 상위 top_n 종목을 반환한다.

    Args:
        tickers: 전체 탐험 대상 티커 리스트
        top_n: 최종 선별 종목 수 (기본 30)
        defense_min: 방산 종목 최소 보장 수 (기본 5)

    Returns:
        선별된 티커 리스트
    """
    total = len(tickers)
    log.info(f"사전 스크리닝 시작: {total}종목 → 상위 {top_n}종목 선별")
    print(f"\n[사전 스크리닝] {total}종목 빠른 평가 중...")

    results: list[tuple[str, float, bool]] = []
    for i, ticker in enumerate(tickers, 1):
        print(f"  {i}/{total} {ticker:<12}", end="\r", flush=True)
        s, d = score_ticker(ticker)
        results.append((ticker, s, d))

    print()

    # 방산 / 일반 분리
    defense = sorted(
        [(t, s, d) for t, s, d in results if d],
        key=lambda x: x[1], reverse=True,
    )
    all_sorted = sorted(results, key=lambda x: x[1], reverse=True)

    # 방산 쿼터: 최소 defense_min개 보장 (점수 0 이상인 것만)
    defense_picks = [x for x in defense if x[1] > 0][:defense_min]
    defense_set = {t for t, s, d in defense_picks}

    # 나머지 슬롯: 방산 제외 후 점수 상위
    remaining_slots = top_n - len(defense_picks)
    other_picks = [x for x in all_sorted if x[0] not in defense_set][:remaining_slots]

    selected = [t for t, s, d in defense_picks + other_picks]

    # 결과 로그
    print(f"\n[사전 스크리닝 완료]")
    print(f"  방산 {len(defense_picks)}개: {[t for t, s, d in defense_picks]}")
    print(f"  일반 {len(other_picks)}개 (상위 5): {[t for t, s, d in other_picks[:5]]}")
    print(f"  → 총 {len(selected)}개 풀 분석 진행\n")

    return selected
