"""백테스트: 과거 시점 분석 → 이후 실제 수익률로 신호 실효성 검증.

사용법:
    python scripts/backtest.py                    # 기본: US_LARGE_CAP, 3개월 전 시점
    python scripts/backtest.py --months-ago 6     # 6개월 전 시점
    python scripts/backtest.py --tickers AAPL MSFT NVDA
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.models import Signal
from src.agents.moderator import ExplorationModerator
from src.pipeline.context_builder import build_context
from src.utils.config import US_LARGE_CAP, GROWTH_CANDIDATES


def get_price_at(ticker: str, target_date: datetime) -> float | None:
    """특정 날짜 근처의 종가를 가져온다 (±5일 허용)."""
    try:
        start = target_date - timedelta(days=7)
        end = target_date + timedelta(days=7)
        t = yf.Ticker(ticker)
        hist = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if hist.empty:
            return None
        # target_date에 가장 가까운 날짜
        closest_idx = min(hist.index, key=lambda d: abs(d.tz_localize(None) - target_date))
        return float(hist.loc[closest_idx, "Close"])
    except Exception:
        return None


def get_current_price(ticker: str) -> float | None:
    """현재가를 가져온다."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        return info.get("currentPrice") or info.get("regularMarketPrice")
    except Exception:
        return None


def run_backtest(tickers: list[str], months_ago: int = 3) -> list[dict]:
    """백테스트를 실행한다."""
    signal_date = datetime.now() - timedelta(days=months_ago * 30)
    results = []

    print(f"\n백테스트: {months_ago}개월 전 ({signal_date.strftime('%Y-%m-%d')}) 기준 분석")
    print(f"대상: {len(tickers)}개 종목")
    print("=" * 70)

    for i, ticker in enumerate(tickers, 1):
        print(f"\n[{i}/{len(tickers)}] {ticker}", end="", flush=True)

        # 1. 현재 기준으로 분석 실행 (과거 재무제표는 yfinance가 자동 반영)
        try:
            context = build_context(ticker)
            moderator = ExplorationModerator()
            result = moderator.run(context)
            signal = result.final_signal.value
            confidence = result.final_confidence
        except Exception as e:
            print(f" — 분석 실패: {e}")
            continue

        # 2. 과거 시점 가격 & 현재 가격
        past_price = get_price_at(ticker, signal_date)
        current_price = get_current_price(ticker)

        if past_price is None or current_price is None:
            print(f" — 가격 데이터 없음 (past={past_price}, current={current_price})")
            continue

        actual_return = (current_price - past_price) / past_price

        entry = {
            "ticker": ticker,
            "signal": signal,
            "confidence": confidence,
            "past_price": past_price,
            "current_price": current_price,
            "actual_return_pct": actual_return * 100,
            "signal_date": signal_date.strftime("%Y-%m-%d"),
        }
        results.append(entry)
        print(f" — {signal:<12} conf={confidence:.2f}  "
              f"${past_price:.1f}→${current_price:.1f} ({actual_return:+.1%})")

    return results


def analyze_results(results: list[dict], months_ago: int) -> None:
    """신호별 수익률 분석 및 요약 출력."""
    if not results:
        print("\n분석 결과 없음.")
        return

    # 신호별 그룹핑
    SIGNAL_ORDER = ["strong_buy", "buy", "watch", "pass", "avoid"]
    signal_groups: dict[str, list[dict]] = {s: [] for s in SIGNAL_ORDER}
    for r in results:
        if r["signal"] in signal_groups:
            signal_groups[r["signal"]].append(r)

    print(f"\n{'=' * 70}")
    print(f"  백테스트 결과 요약 ({months_ago}개월 전 기준)")
    print(f"{'=' * 70}")
    print(f"  {'신호':<14}{'종목수':<8}{'평균수익률':<14}{'승률':<10}{'최고':<12}{'최저'}")
    print(f"  {'-' * 64}")

    all_returns = []
    signal_avg = {}

    for sig in SIGNAL_ORDER:
        group = signal_groups[sig]
        if not group:
            print(f"  {sig:<14}{'—':<8}")
            continue

        returns = [r["actual_return_pct"] for r in group]
        avg_ret = sum(returns) / len(returns)
        win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100
        max_ret = max(returns)
        min_ret = min(returns)

        signal_avg[sig] = avg_ret
        all_returns.extend(returns)

        print(f"  {sig:<14}{len(group):<8}{avg_ret:+.1f}%{'':>6}"
              f"{win_rate:.0f}%{'':>5}{max_ret:+.1f}%{'':>5}{min_ret:+.1f}%")

    print(f"  {'-' * 64}")
    if all_returns:
        total_avg = sum(all_returns) / len(all_returns)
        print(f"  {'전체':<14}{len(results):<8}{total_avg:+.1f}%")

    # 실효성 판단
    print(f"\n{'=' * 70}")
    print("  실효성 판단")
    print(f"{'=' * 70}")

    positive_signals = ["strong_buy", "buy"]
    negative_signals = ["pass", "avoid"]

    pos_returns = [r["actual_return_pct"] for r in results if r["signal"] in positive_signals]
    neg_returns = [r["actual_return_pct"] for r in results if r["signal"] in negative_signals]

    if pos_returns and neg_returns:
        pos_avg = sum(pos_returns) / len(pos_returns)
        neg_avg = sum(neg_returns) / len(neg_returns)
        spread = pos_avg - neg_avg
        print(f"  매수 신호 평균 수익률: {pos_avg:+.1f}% ({len(pos_returns)}종목)")
        print(f"  회피 신호 평균 수익률: {neg_avg:+.1f}% ({len(neg_returns)}종목)")
        print(f"  스프레드: {spread:+.1f}%p")

        if spread > 5:
            print(f"\n  결론: 신호 실효성 있음 (매수-회피 스프레드 {spread:+.1f}%p)")
        elif spread > 0:
            print(f"\n  결론: 약한 실효성 (스프레드 {spread:+.1f}%p — 개선 필요)")
        else:
            print(f"\n  결론: 실효성 미확인 (역방향 스프레드 {spread:+.1f}%p)")
    elif pos_returns:
        pos_avg = sum(pos_returns) / len(pos_returns)
        pos_win = sum(1 for r in pos_returns if r > 0) / len(pos_returns) * 100
        print(f"  매수 신호 평균 수익률: {pos_avg:+.1f}% (승률 {pos_win:.0f}%)")
        print("  회피 신호 데이터 부족 — 스프레드 비교 불가")
    else:
        print("  데이터 부족 — 판단 불가")

    # 개별 종목 랭킹
    print(f"\n{'=' * 70}")
    print("  개별 종목 상세 (수익률 순)")
    print(f"{'=' * 70}")
    print(f"  {'#':<4}{'종목':<10}{'신호':<14}{'확신도':<9}{'수익률':<12}{'가격변동'}")
    print(f"  {'-' * 64}")

    sorted_results = sorted(results, key=lambda r: r["actual_return_pct"], reverse=True)
    for idx, r in enumerate(sorted_results, 1):
        print(f"  {idx:<4}{r['ticker']:<10}{r['signal']:<14}{r['confidence']:.2f}     "
              f"{r['actual_return_pct']:+.1f}%{'':>5}"
              f"${r['past_price']:.1f}→${r['current_price']:.1f}")


def main():
    parser = argparse.ArgumentParser(description="신호 실효성 백테스트")
    parser.add_argument("--tickers", nargs="*", help="백테스트 대상 종목")
    parser.add_argument("--months-ago", type=int, default=3, help="몇 개월 전 기준 (기본: 3)")
    parser.add_argument("--universe", action="store_true", help="US_LARGE_CAP 전체")
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
    elif args.universe:
        tickers = US_LARGE_CAP
    else:
        # 기본: 대표 종목 15개
        tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
                    "JPM", "V", "UNH", "JNJ", "XOM", "HD", "COST",
                    "PLTR", "CRWD"]

    results = run_backtest(tickers, months_ago=args.months_ago)
    analyze_results(results, months_ago=args.months_ago)


if __name__ == "__main__":
    main()
