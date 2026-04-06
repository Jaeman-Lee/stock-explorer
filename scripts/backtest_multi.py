#!/usr/bin/env python3
"""Phase 1: 다기간 × 다전략 백테스트.

과거 N개월 전 시점에서 에이전트 평가를 1회 실행하고,
9개 전략별 신호를 동시 비교하여 스프레드/승률을 산출한다.

에이전트 의견은 JSON 캐시에 저장하여 Phase 2/4에서 재사용한다.

Usage:
    python scripts/backtest_multi.py                          # 기본 30종목 × [3,6,9,12]개월
    python scripts/backtest_multi.py --months 3 6             # 특정 시점만
    python scripts/backtest_multi.py --tickers AAPL MSFT      # 특정 종목만
    python scripts/backtest_multi.py --cache-only             # 캐시 데이터로만 분석 (API 없음)
    python scripts/backtest_multi.py --strategies v3 v6 auto  # 특정 전략만 비교
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.models import AgentOpinion, Signal, StockAnalysisContext
from src.agents.moderator import ExplorationModerator
from src.agents.signal_strategy import (
    STRATEGIES,
    REGIME_STRATEGY_MAP,
    apply_strategy,
    get_strategy,
    _legacy_signal,
)
from src.pipeline.context_builder import build_context
from src.utils.config import US_LARGE_CAP, GROWTH_CANDIDATES, KR_STOCKS

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

POSITIVE = {Signal.STRONG_BUY, Signal.BUY}
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "backtest_cache"

# ── 대상 종목 ─────────────────────────────────────────────────────────────────

DEFAULT_TICKERS = (
    US_LARGE_CAP
    + ["005930.KS", "000660.KS", "035420.KS"]
    + ["AMD", "AVGO", "LLY", "MA", "ADBE", "GE"]
)
# 중복 제거
DEFAULT_TICKERS = list(dict.fromkeys(DEFAULT_TICKERS))

DEFAULT_MONTHS = [3, 6, 9, 12]


# ── 가격 조회 ─────────────────────────────────────────────────────────────────

def get_price_at(ticker: str, target_date: datetime) -> float | None:
    """특정 날짜 근처의 종가 (±7일 허용)."""
    try:
        start = (target_date - timedelta(days=10)).strftime("%Y-%m-%d")
        end = (target_date + timedelta(days=7)).strftime("%Y-%m-%d")
        t = yf.Ticker(ticker)
        hist = t.history(start=start, end=end)
        if hist is None or hist.empty:
            return None
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
        closest = min(hist.index, key=lambda d: abs(d - target_date))
        return float(hist.loc[closest, "Close"])
    except Exception:
        return None


def get_current_price(ticker: str) -> float | None:
    """최근 5일 종가."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        if hist is None or hist.empty:
            return None
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


# ── 매크로 레짐 판정 ──────────────────────────────────────────────────────────

def get_regime_at(target_date: datetime) -> str:
    """과거 시점의 매크로 레짐을 판정한다."""
    try:
        start = (target_date - timedelta(days=70)).strftime("%Y-%m-%d")
        end = (target_date + timedelta(days=2)).strftime("%Y-%m-%d")
        sp = yf.Ticker("^GSPC")
        sp_hist = sp.history(start=start, end=end)
        if sp_hist is None or sp_hist.empty:
            return "neutral"
        if isinstance(sp_hist.columns, pd.MultiIndex):
            sp_hist.columns = sp_hist.columns.get_level_values(0)
        sp_hist.index = sp_hist.index.tz_localize(None) if sp_hist.index.tz else sp_hist.index
        sp_close = sp_hist["Close"].dropna()
        if len(sp_close) < 10:
            return "neutral"
        current_sp = float(sp_close.iloc[-1])
        sma50 = float(sp_close.tail(50).mean())

        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(start=(target_date - timedelta(days=7)).strftime("%Y-%m-%d"), end=end)
        if vix_hist is None or vix_hist.empty:
            return "neutral"
        if isinstance(vix_hist.columns, pd.MultiIndex):
            vix_hist.columns = vix_hist.columns.get_level_values(0)
        vix_hist.index = vix_hist.index.tz_localize(None) if vix_hist.index.tz else vix_hist.index
        vix_close = vix_hist["Close"].dropna()
        if len(vix_close) < 1:
            return "neutral"
        current_vix = float(vix_close.iloc[-1])

        if current_vix > 25 and current_sp < sma50:
            return "bear"
        elif current_vix < 18 and current_sp > sma50:
            return "bull"
        return "neutral"
    except Exception:
        return "neutral"


# ── 캐시 ──────────────────────────────────────────────────────────────────────

def _cache_path(ticker: str, signal_date: str) -> Path:
    return CACHE_DIR / f"{ticker}_{signal_date}.json"


def _save_cache(ticker: str, signal_date: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(ticker, signal_date)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_cache(ticker: str, signal_date: str) -> dict | None:
    path = _cache_path(ticker, signal_date)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


# ── 에이전트 실행 + 캐시 ──────────────────────────────────────────────────────

def run_agents_for_ticker(ticker: str, signal_date_str: str, cache_only: bool = False) -> dict | None:
    """에이전트 평가를 실행하고 결과를 캐시한다. 캐시가 있으면 재사용."""
    cached = _load_cache(ticker, signal_date_str)
    if cached:
        return cached

    if cache_only:
        return None

    try:
        context = build_context(ticker)
    except Exception as e:
        logger.warning("[%s] context 실패: %s", ticker, e)
        return None

    moderator = ExplorationModerator(strategy="legacy")
    try:
        # Phase 1만 실행하여 opinions 수집
        opinions = moderator._collect_opinions(context)
    except Exception as e:
        logger.warning("[%s] 에이전트 실패: %s", ticker, e)
        return None

    # opinions를 직렬화
    opinions_data = []
    for o in opinions:
        opinions_data.append({
            "agent": o.agent_name,
            "signal": o.signal.value,
            "confidence": o.confidence,
            "rationale": o.rationale,
            "risk_flags": o.risk_flags,
            "strengths": o.strengths,
        })

    # 가격 수집
    signal_dt = datetime.strptime(signal_date_str, "%Y-%m-%d")
    price_at = get_price_at(ticker, signal_dt)
    price_now = get_current_price(ticker)
    return_pct = None
    if price_at and price_now:
        return_pct = (price_now - price_at) / price_at * 100

    # 매크로 레짐
    regime = get_regime_at(signal_dt)

    data = {
        "ticker": ticker,
        "signal_date": signal_date_str,
        "regime": regime,
        "opinions": opinions_data,
        "price_at_signal": price_at,
        "price_current": price_now,
        "return_pct": round(return_pct, 2) if return_pct is not None else None,
        "cached_at": datetime.now().isoformat(timespec="seconds"),
    }

    _save_cache(ticker, signal_date_str, data)
    return data


# ── 전략별 신호 계산 ──────────────────────────────────────────────────────────

def opinions_from_cache(data: dict) -> list[AgentOpinion]:
    """캐시 데이터에서 AgentOpinion 리스트를 복원한다."""
    opinions = []
    for o in data["opinions"]:
        opinions.append(AgentOpinion(
            agent_name=o["agent"],
            signal=Signal(o["signal"]),
            confidence=o["confidence"],
            rationale=o.get("rationale", ""),
            risk_flags=o.get("risk_flags", []),
            strengths=o.get("strengths", []),
        ))
    return opinions


def compute_strategy_signals(data: dict, strategy_names: list[str]) -> dict[str, str]:
    """캐시 데이터에 대해 전략별 신호를 계산한다."""
    opinions = opinions_from_cache(data)
    regime = data.get("regime", "neutral")
    signals = {}

    for name in strategy_names:
        if name == "auto":
            params = get_strategy("auto", macro_regime=regime)
        elif name == "legacy":
            signals["legacy"] = _legacy_signal(opinions).value
            continue
        else:
            params = STRATEGIES.get(name)
            if not params:
                continue

        sig, _ = apply_strategy(params, opinions, macro_regime=regime)
        signals[name] = sig.value

    return signals


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 1: 다기간 × 다전략 백테스트")
    parser.add_argument("--tickers", nargs="*", help="백테스트 종목")
    parser.add_argument("--months", nargs="*", type=int, default=DEFAULT_MONTHS, help="시점 (개월 전)")
    parser.add_argument("--cache-only", action="store_true", help="캐시 데이터만 사용 (API 호출 없음)")
    parser.add_argument("--strategies", nargs="*", default=None,
                        help="비교할 전략 (기본: legacy v1 v3 v6 v3-bear auto)")
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers] if args.tickers else DEFAULT_TICKERS
    months_list = args.months
    strategy_names = args.strategies or ["legacy", "v1", "v3", "v6", "v3-bear", "auto"]

    now = datetime.now()

    print(f"Phase 1: 다기간 백테스트")
    print(f"종목: {len(tickers)}개 | 시점: {months_list}개월 전 | 전략: {', '.join(strategy_names)}")
    print("=" * 100)

    # ── 데이터 수집 ──
    all_data: list[dict] = []  # {ticker, months, signal_date, regime, return_pct, strategies: {name: signal}}
    total = len(tickers) * len(months_list)
    done = 0

    for months in months_list:
        signal_dt = now - timedelta(days=months * 30)
        signal_date_str = signal_dt.strftime("%Y-%m-%d")
        print(f"\n--- {months}개월 전 ({signal_date_str}) ---")

        for ticker in tickers:
            done += 1
            print(f"\r  [{done}/{total}] {ticker:<12}", end="", flush=True)

            data = run_agents_for_ticker(ticker, signal_date_str, cache_only=args.cache_only)
            if data is None:
                continue

            # 전략별 신호 계산
            strat_signals = compute_strategy_signals(data, strategy_names)

            all_data.append({
                "ticker": ticker,
                "months": months,
                "signal_date": signal_date_str,
                "regime": data.get("regime", "neutral"),
                "return_pct": data.get("return_pct"),
                "price_at": data.get("price_at_signal"),
                "price_now": data.get("price_current"),
                "strategies": strat_signals,
            })

        print()

    # ── 분석 ──
    print(f"\n{'=' * 100}")
    print(f"  전략별 성과 비교")
    print(f"{'=' * 100}\n")

    # 시점별 × 전략별 매트릭스
    header = f"{'전략':<16}"
    for m in months_list:
        header += f"| {m}개월 spread  승률     "
    header += "| 전체 spread  승률"
    print(header)
    print("-" * len(header))

    for sname in strategy_names:
        line = f"{sname:<16}"

        all_buy_returns = []
        all_nonbuy_returns = []

        for m in months_list:
            rows = [d for d in all_data if d["months"] == m and d["return_pct"] is not None]
            buys = [d for d in rows if d["strategies"].get(sname) in ("strong_buy", "buy")]
            non_buys = [d for d in rows if d["strategies"].get(sname) not in ("strong_buy", "buy")]

            avg_buy = sum(d["return_pct"] for d in buys) / len(buys) if buys else 0
            avg_non = sum(d["return_pct"] for d in non_buys) / len(non_buys) if non_buys else 0
            spread = avg_buy - avg_non if non_buys else 0
            win = sum(1 for d in buys if d["return_pct"] > 0)
            win_rate = win / len(buys) * 100 if buys else 0
            buy_n = len(buys)

            line += f"| {spread:>+6.1f}%p {win:>2}/{buy_n:<2}({win_rate:>3.0f}%) "

            all_buy_returns.extend(d["return_pct"] for d in buys)
            all_nonbuy_returns.extend(d["return_pct"] for d in non_buys)

        # 전체
        total_avg_buy = sum(all_buy_returns) / len(all_buy_returns) if all_buy_returns else 0
        total_avg_non = sum(all_nonbuy_returns) / len(all_nonbuy_returns) if all_nonbuy_returns else 0
        total_spread = total_avg_buy - total_avg_non if all_nonbuy_returns else 0
        total_win = sum(1 for r in all_buy_returns if r > 0)
        total_win_rate = total_win / len(all_buy_returns) * 100 if all_buy_returns else 0
        total_n = len(all_buy_returns)

        line += f"| {total_spread:>+6.1f}%p {total_win:>2}/{total_n:<3}({total_win_rate:>3.0f}%)"
        print(line)

    # ── 신호 분포 ──
    print(f"\n{'=' * 100}")
    print(f"  전략별 BUY 비율 (시점 통합)")
    print(f"{'=' * 100}\n")

    valid = [d for d in all_data if d["return_pct"] is not None]
    total_valid = len(valid)

    header2 = f"{'전략':<16} {'BUY이상':>8} {'비율':>6} {'SB':>5} {'BUY':>5} {'WATCH':>6} {'PASS':>6} {'AVOID':>6}"
    print(header2)
    print("-" * len(header2))

    for sname in strategy_names:
        from collections import Counter
        dist = Counter(d["strategies"].get(sname, "?") for d in valid)
        buy_n = dist.get("strong_buy", 0) + dist.get("buy", 0)
        ratio = buy_n / total_valid * 100 if total_valid else 0
        print(f"{sname:<16} {buy_n:>6}개 {ratio:>5.0f}% "
              f"{dist.get('strong_buy', 0):>5} {dist.get('buy', 0):>5} "
              f"{dist.get('watch', 0):>6} {dist.get('pass', 0):>6} {dist.get('avoid', 0):>6}")

    # ── 레짐별 분포 ──
    print(f"\n{'=' * 100}")
    print(f"  시점별 매크로 레짐")
    print(f"{'=' * 100}\n")

    for m in months_list:
        signal_dt = now - timedelta(days=m * 30)
        rows = [d for d in all_data if d["months"] == m]
        if rows:
            regime = rows[0]["regime"]
            print(f"  {m:>2}개월 전 ({signal_dt.strftime('%Y-%m-%d')}): {regime}")

    # 캐시 통계
    cached_files = list(CACHE_DIR.glob("*.json")) if CACHE_DIR.exists() else []
    print(f"\n캐시: {len(cached_files)}개 파일 ({CACHE_DIR})")


if __name__ == "__main__":
    main()
