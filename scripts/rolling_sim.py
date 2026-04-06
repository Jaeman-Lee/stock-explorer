#!/usr/bin/env python3
"""Phase 3: 롤링 시뮬레이션.

과거 12개월을 4주 단위로 롤링하며, 매 시점 전략별 BUY 종목의
다음 4주 수익률을 누적한다. 누적 수익 곡선 + 샤프/낙폭 산출.

Phase 1 캐시가 있는 시점은 재사용, 없으면 에이전트 실행.

Usage:
    python scripts/rolling_sim.py                          # 기본: 12개월, 4주 간격
    python scripts/rolling_sim.py --weeks 26 --interval 2  # 26주, 2주 간격
    python scripts/rolling_sim.py --cache-only             # 캐시만 사용
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.models import AgentOpinion, Signal
from src.agents.signal_strategy import (
    STRATEGIES, apply_strategy, get_strategy, _legacy_signal,
)

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "backtest_cache"
POSITIVE = {"strong_buy", "buy"}

# 핵심 종목 (API 호출 최소화를 위해 축소)
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSM",
    "JPM", "BRK-B", "V", "MA",
    "UNH", "JNJ", "LLY",
    "COST", "HD", "NKE",
    "XOM", "CVX",
    "T", "VZ",
]

STRATEGIES_TO_TEST = ["legacy", "v3", "v6", "auto"]


def get_price_range(ticker: str, start: str, end: str) -> dict[str, float]:
    """기간 내 주별 종가를 dict로 반환."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(start=start, end=end, interval="1wk")
        if hist is None or hist.empty:
            return {}
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
        return {d.strftime("%Y-%m-%d"): float(hist.loc[d, "Close"]) for d in hist.index}
    except Exception:
        return {}


def get_regime_at(target_date: datetime) -> str:
    """시점 매크로 레짐 판정."""
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
        current_vix = float(vix_hist["Close"].dropna().iloc[-1])

        if current_vix > 25 and current_sp < sma50:
            return "bear"
        elif current_vix < 18 and current_sp > sma50:
            return "bull"
        return "neutral"
    except Exception:
        return "neutral"


def load_or_run_opinions(ticker: str, date_str: str) -> list[AgentOpinion] | None:
    """캐시에서 opinions 로드. 없으면 None."""
    cache_path = CACHE_DIR / f"{ticker}_{date_str}.json"
    if cache_path.exists():
        with open(cache_path) as f:
            data = json.load(f)
        opinions = []
        for o in data["opinions"]:
            opinions.append(AgentOpinion(
                agent_name=o["agent"], signal=Signal(o["signal"]),
                confidence=o["confidence"], rationale="",
                risk_flags=o.get("risk_flags", []), strengths=o.get("strengths", []),
            ))
        return opinions
    return None


def main():
    parser = argparse.ArgumentParser(description="Phase 3: 롤링 시뮬레이션")
    parser.add_argument("--weeks", type=int, default=52, help="롤링 기간 (주)")
    parser.add_argument("--interval", type=int, default=4, help="리밸런싱 간격 (주)")
    parser.add_argument("--cache-only", action="store_true", help="캐시만 사용")
    args = parser.parse_args()

    now = datetime.now()
    interval_days = args.interval * 7

    # 롤링 시점 생성
    periods = []
    for i in range(0, args.weeks, args.interval):
        entry_date = now - timedelta(days=(args.weeks - i) * 7)
        exit_date = entry_date + timedelta(days=interval_days)
        if exit_date > now:
            exit_date = now
        periods.append({
            "entry": entry_date,
            "exit": exit_date,
            "entry_str": entry_date.strftime("%Y-%m-%d"),
            "exit_str": exit_date.strftime("%Y-%m-%d"),
        })

    print(f"Phase 3: 롤링 시뮬레이션")
    print(f"종목: {len(TICKERS)}개 | 기간: {args.weeks}주 | 간격: {args.interval}주 | 시점: {len(periods)}개")
    print("=" * 100)

    # 가격 데이터 사전 수집 (전체 기간 한 번에)
    overall_start = (now - timedelta(days=args.weeks * 7 + 14)).strftime("%Y-%m-%d")
    overall_end = (now + timedelta(days=7)).strftime("%Y-%m-%d")

    print("가격 데이터 수집 중...", end="", flush=True)
    price_data: dict[str, dict[str, float]] = {}
    for ticker in TICKERS:
        price_data[ticker] = get_price_range(ticker, overall_start, overall_end)
    print(" 완료")

    # S&P500 가격도 수집
    sp_prices = get_price_range("^GSPC", overall_start, overall_end)

    # 롤링 실행
    # 각 전략별 period_return을 누적
    strategy_returns: dict[str, list[float]] = {s: [] for s in STRATEGIES_TO_TEST}
    sp_returns: list[float] = []
    period_details: list[dict] = []

    for pidx, period in enumerate(periods):
        entry_dt = period["entry"]
        exit_dt = period["exit"]
        entry_str = period["entry_str"]

        # 매크로 레짐
        regime = get_regime_at(entry_dt)

        # 각 종목의 entry/exit 가격 찾기
        ticker_returns: dict[str, float] = {}
        for ticker in TICKERS:
            prices = price_data.get(ticker, {})
            if not prices:
                continue
            # entry_str에 가장 가까운 가격
            entry_candidates = [(d, p) for d, p in prices.items() if d <= entry_str]
            exit_candidates = [(d, p) for d, p in prices.items()
                               if d >= entry_str and d <= period["exit_str"]]
            if not entry_candidates or not exit_candidates:
                continue
            entry_price = max(entry_candidates, key=lambda x: x[0])[1]
            exit_price = max(exit_candidates, key=lambda x: x[0])[1]
            ticker_returns[ticker] = (exit_price - entry_price) / entry_price * 100

        # S&P500 return
        sp_entry = [(d, p) for d, p in sp_prices.items() if d <= entry_str]
        sp_exit = [(d, p) for d, p in sp_prices.items()
                   if d >= entry_str and d <= period["exit_str"]]
        sp_ret = 0.0
        if sp_entry and sp_exit:
            sp_ret = (max(sp_exit, key=lambda x: x[0])[1] - max(sp_entry, key=lambda x: x[0])[1]) / max(sp_entry, key=lambda x: x[0])[1] * 100
        sp_returns.append(sp_ret)

        # Phase 1 캐시에서 opinions 로드 (가장 가까운 날짜)
        # 캐시가 없는 시점은 해당 period 스킵
        period_has_data = False
        strategy_period_returns: dict[str, list[float]] = {s: [] for s in STRATEGIES_TO_TEST}

        for ticker in TICKERS:
            if ticker not in ticker_returns:
                continue
            opinions = load_or_run_opinions(ticker, entry_str)
            if opinions is None:
                # 근처 날짜 캐시 탐색 (±7일)
                for delta in range(-7, 8):
                    alt_date = (entry_dt + timedelta(days=delta)).strftime("%Y-%m-%d")
                    opinions = load_or_run_opinions(ticker, alt_date)
                    if opinions:
                        break
            if opinions is None:
                continue

            period_has_data = True

            for sname in STRATEGIES_TO_TEST:
                if sname == "legacy":
                    sig = _legacy_signal(opinions).value
                elif sname == "auto":
                    params = get_strategy("auto", macro_regime=regime)
                    sig, _ = apply_strategy(params, opinions, macro_regime=regime)
                    sig = sig.value
                else:
                    params = STRATEGIES[sname]
                    sig, _ = apply_strategy(params, opinions, macro_regime=regime)
                    sig = sig.value

                if sig in POSITIVE:
                    strategy_period_returns[sname].append(ticker_returns[ticker])

        # 기간별 평균 수익률
        detail = {"period": entry_str, "regime": regime, "sp500": sp_ret}
        for sname in STRATEGIES_TO_TEST:
            rets = strategy_period_returns[sname]
            if rets:
                avg = sum(rets) / len(rets)
                strategy_returns[sname].append(avg)
                detail[sname] = {"avg": avg, "n": len(rets)}
            else:
                strategy_returns[sname].append(0.0)
                detail[sname] = {"avg": 0.0, "n": 0}
        period_details.append(detail)

    # ── 결과 출력 ──
    print(f"\n{'=' * 110}")
    print(f"  기간별 수익률 ({args.interval}주 단위)")
    print(f"{'=' * 110}")

    header = f"{'기간':>12} {'레짐':<8} {'S&P500':>8}"
    for s in STRATEGIES_TO_TEST:
        header += f" {s:>12}"
    print(header)
    print("-" * 110)

    for d in period_details:
        line = f"{d['period']:>12} {d['regime']:<8} {d['sp500']:>+7.1f}%"
        for s in STRATEGIES_TO_TEST:
            info = d[s]
            if info["n"] > 0:
                line += f" {info['avg']:>+7.1f}%({info['n']:>2})"
            else:
                line += f" {'—':>12}"
        print(line)

    # ── 누적 수익 ──
    print(f"\n{'=' * 110}")
    print(f"  누적 수익 곡선")
    print(f"{'=' * 110}")

    cum: dict[str, float] = {s: 100.0 for s in STRATEGIES_TO_TEST}
    cum["S&P500"] = 100.0
    max_vals: dict[str, float] = {s: 100.0 for s in STRATEGIES_TO_TEST}
    max_vals["S&P500"] = 100.0
    max_dd: dict[str, float] = {s: 0.0 for s in STRATEGIES_TO_TEST}
    max_dd["S&P500"] = 0.0

    for i, d in enumerate(period_details):
        cum["S&P500"] *= (1 + sp_returns[i] / 100)
        max_vals["S&P500"] = max(max_vals["S&P500"], cum["S&P500"])
        dd = (cum["S&P500"] - max_vals["S&P500"]) / max_vals["S&P500"] * 100
        max_dd["S&P500"] = min(max_dd["S&P500"], dd)

        for s in STRATEGIES_TO_TEST:
            r = strategy_returns[s][i]
            cum[s] *= (1 + r / 100)
            max_vals[s] = max(max_vals[s], cum[s])
            dd = (cum[s] - max_vals[s]) / max_vals[s] * 100
            max_dd[s] = min(max_dd[s], dd)

    print(f"\n  {'전략':<14} {'누적수익':>10} {'총수익률':>10} {'Max DD':>10} {'샤프(추정)':>12}")
    print(f"  {'-' * 58}")

    for s in ["S&P500"] + STRATEGIES_TO_TEST:
        total_ret = cum[s] - 100
        # 샤프 추정 (연환산)
        if s == "S&P500":
            rets = sp_returns
        else:
            rets = strategy_returns[s]
        if len(rets) > 1:
            mean_r = sum(rets) / len(rets)
            std_r = (sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
            periods_per_year = 52 / args.interval
            sharpe = (mean_r * periods_per_year) / (std_r * math.sqrt(periods_per_year)) if std_r > 0 else 0
        else:
            sharpe = 0

        print(f"  {s:<14} {cum[s]:>9.1f} {total_ret:>+9.1f}% {max_dd[s]:>+9.1f}% {sharpe:>11.2f}")


if __name__ == "__main__":
    main()
