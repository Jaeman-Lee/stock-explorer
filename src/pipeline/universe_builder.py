"""유니버스 빌더.

S&P 500 전체 목록을 Wikipedia에서 수집하고,
DAX 40 / EU 섹터와 합쳐 전체 탐험 대상 유니버스를 반환한다.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# ── S&P 500 Fallback (Wikipedia 접근 실패 시) ─────────────────────────────────
# 시총 상위 ~100 + 대표 섹터 커버
SP500_FALLBACK = [
    # 메가캡 테크
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "QCOM", "INTC", "TXN", "AMAT", "LRCX", "KLAC", "SNPS", "CDNS",
    "NOW", "PANW", "FTNT", "CRWD", "NET", "ZS", "DDOG", "MDB", "SNOW",
    # 금융
    "BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "AXP", "BX",
    "SPGI", "MCO", "CME", "ICE", "FI", "PYPL", "COF",
    # 헬스케어
    "LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "SYK",
    "ISRG", "VRTX", "REGN", "GILD", "CI", "EW", "ZTS", "IDXX",
    # 소비재/필수소비재
    "COST", "WMT", "HD", "MCD", "SBUX", "NKE", "TJX", "LOW", "TGT",
    "PG", "KO", "PEP", "MDLZ", "CL", "EL",
    # 산업재/방산
    "GE", "CAT", "DE", "HON", "MMM", "ETN", "ITW", "EMR", "PH",
    "LMT", "RTX", "NOC", "GD", "LHX", "BA",
    # 에너지
    "XOM", "CVX", "COP", "EOG", "SLB", "OXY", "PSX", "VLO", "MPC", "HAL",
    # 통신/미디어
    "T", "VZ", "NFLX", "DIS", "CMCSA", "CHTR",
    # 리츠/유틸리티
    "NEE", "DUK", "SO", "PLD", "AMT", "CCI",
    # 헬스케어 추가
    "HUM", "CVS", "MCK", "AmerisourceBergen",
    # 성장주
    "PLTR", "SHOP", "MELI", "SE", "OKTA",
]


def get_sp500(use_wikipedia: bool = True) -> list[str]:
    """S&P 500 전체 티커 목록을 반환한다.

    Wikipedia 수집 성공 시 전체 503개, 실패 시 fallback 리스트 사용.
    """
    if use_wikipedia:
        try:
            import pandas as pd
            tables = pd.read_html(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                attrs={"id": "constituents"},
            )
            df = tables[0]
            tickers = (
                df["Symbol"]
                .str.replace(".", "-", regex=False)
                .tolist()
            )
            log.info(f"S&P 500: Wikipedia에서 {len(tickers)}개 수집")
            return tickers
        except Exception as e:
            log.warning(f"Wikipedia 수집 실패 ({e}), fallback 사용")

    log.info(f"S&P 500: fallback {len(SP500_FALLBACK)}개 사용")
    return SP500_FALLBACK


def build_full_universe(include_eu: bool = True) -> list[str]:
    """S&P 500 + DAX 40 + EU 섹터 전체 유니버스를 반환한다."""
    from src.utils.config import DAX40, EU_DEFENSE, EU_ENERGY, EU_TECH

    sp500 = get_sp500()
    seen = set(sp500)
    result = list(sp500)

    if include_eu:
        for ticker in DAX40 + EU_DEFENSE + EU_ENERGY + EU_TECH:
            if ticker not in seen:
                seen.add(ticker)
                result.append(ticker)

    log.info(f"전체 유니버스: {len(result)}개 (S&P500 {len(sp500)} + EU {len(result)-len(sp500)})")
    return result
