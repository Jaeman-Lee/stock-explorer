#!/usr/bin/env python3
"""Phase 2: 시장 구간별(레짐별) 전략 성과 분석.

Phase 1 캐시 데이터를 읽어 bull/neutral/bear 구간으로 분류하고,
레짐 × 전략 매트릭스를 생성한다. auto 선택 vs 고정 전략 vs oracle(사후 최적) 비교.

Usage:
    python scripts/regime_analysis.py                # Phase 1 캐시 기반 분석
    python scripts/regime_analysis.py --detail       # 종목별 상세 출력
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.models import AgentOpinion, Signal
from src.agents.signal_strategy import (
    STRATEGIES,
    REGIME_STRATEGY_MAP,
    apply_strategy,
    get_strategy,
    _legacy_signal,
)

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "backtest_cache"
POSITIVE = {"strong_buy", "buy"}
ALL_STRATEGIES = ["legacy", "v1", "v2", "v3", "v4", "v5", "v6", "v3-bear", "v3-defensive"]


def load_cache() -> list[dict]:
    """Phase 1 캐시 파일을 모두 로드한다."""
    results = []
    for f in sorted(CACHE_DIR.glob("*.json")):
        with open(f) as fp:
            data = json.load(fp)
        if data.get("return_pct") is None:
            continue
        results.append(data)
    return results


def opinions_from_data(data: dict) -> list[AgentOpinion]:
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


def compute_all_signals(data: dict) -> dict[str, str]:
    """모든 전략의 신호를 계산한다."""
    opinions = opinions_from_data(data)
    regime = data.get("regime", "neutral")
    signals = {}

    # legacy
    signals["legacy"] = _legacy_signal(opinions).value

    # v1~v6, v3-bear, v3-defensive
    for name in ALL_STRATEGIES:
        if name == "legacy":
            continue
        params = STRATEGIES.get(name)
        if not params:
            continue
        sig, _ = apply_strategy(params, opinions, macro_regime=regime)
        signals[name] = sig.value

    # auto
    auto_params = get_strategy("auto", macro_regime=regime)
    sig, _ = apply_strategy(auto_params, opinions, macro_regime=regime)
    signals["auto"] = sig.value

    # oracle: 각 레짐에서 사후적으로 최적 전략 선택 (Phase 2 후 결정)
    # → 일단 전 전략 중 실제 수익률 기준 최적을 나중에 계산

    return signals


def compute_stats(rows: list[dict], sname: str) -> dict:
    """특정 전략의 BUY 종목 성과를 계산한다."""
    buys = [r for r in rows if r["signals"].get(sname) in POSITIVE]
    non_buys = [r for r in rows if r["signals"].get(sname) not in POSITIVE]

    if not buys:
        return {"buy_n": 0, "avg_buy": 0, "win": 0, "win_rate": 0, "spread": 0, "avg_non": 0, "non_n": 0}

    avg_buy = sum(r["return_pct"] for r in buys) / len(buys)
    avg_non = sum(r["return_pct"] for r in non_buys) / len(non_buys) if non_buys else 0
    win = sum(1 for r in buys if r["return_pct"] > 0)

    return {
        "buy_n": len(buys),
        "non_n": len(non_buys),
        "avg_buy": avg_buy,
        "avg_non": avg_non,
        "win": win,
        "win_rate": win / len(buys) * 100,
        "spread": avg_buy - avg_non if non_buys else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 2: 레짐별 전략 성과 분석")
    parser.add_argument("--detail", action="store_true", help="종목별 상세 출력")
    args = parser.parse_args()

    raw_data = load_cache()
    print(f"캐시 로드: {len(raw_data)}건\n")

    # 전 전략 신호 계산
    enriched = []
    for d in raw_data:
        signals = compute_all_signals(d)
        enriched.append({
            "ticker": d["ticker"],
            "signal_date": d["signal_date"],
            "regime": d.get("regime", "neutral"),
            "return_pct": d["return_pct"],
            "signals": signals,
        })

    # 레짐별 분류
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for r in enriched:
        by_regime[r["regime"]].append(r)

    compare_strategies = ["legacy", "v1", "v3", "v6", "v3-bear", "v3-defensive", "auto"]

    # ── 레짐 × 전략 매트릭스 ──
    print("=" * 120)
    print("  레짐 × 전략 성과 매트릭스 (스프레드 %p)")
    print("=" * 120)

    # S&P500 기준 수익률도 같이 표기
    regimes = ["bull", "neutral", "bear"]

    header = f"{'전략':<18}"
    for regime in regimes:
        n = len(by_regime.get(regime, []))
        header += f"| {regime:^8}({n:>3}건) "
    header += f"| {'전체':^12}"
    print(header)
    print("-" * len(header))

    # 각 전략별 레짐별 스프레드
    strategy_regime_stats: dict[str, dict[str, dict]] = {}
    for sname in compare_strategies:
        strategy_regime_stats[sname] = {}
        line = f"{sname:<18}"

        for regime in regimes:
            rows = by_regime.get(regime, [])
            if rows:
                stats = compute_stats(rows, sname)
                strategy_regime_stats[sname][regime] = stats
                line += f"| {stats['spread']:>+6.1f}%p {stats['win']:>2}/{stats['buy_n']:<2} "
            else:
                line += f"| {'—':>14} "

        # 전체
        all_stats = compute_stats(enriched, sname)
        strategy_regime_stats[sname]["all"] = all_stats
        line += f"| {all_stats['spread']:>+6.1f}%p {all_stats['win']:>2}/{all_stats['buy_n']:<3}"
        print(line)

    # ── 레짐별 BUY 평균 수익률 ──
    print(f"\n{'=' * 120}")
    print("  레짐 × 전략 BUY 평균 수익률 (%)")
    print("=" * 120)

    header2 = f"{'전략':<18}"
    for regime in regimes:
        header2 += f"| {regime:^16} "
    header2 += f"| {'전체':^12}"
    print(header2)
    print("-" * len(header2))

    for sname in compare_strategies:
        line = f"{sname:<18}"
        for regime in regimes:
            stats = strategy_regime_stats[sname].get(regime, {})
            if stats and stats.get("buy_n", 0) > 0:
                line += f"| {stats['avg_buy']:>+7.1f}% ({stats['buy_n']:>2}) "
            else:
                line += f"| {'—':>16} "
        all_s = strategy_regime_stats[sname].get("all", {})
        if all_s and all_s.get("buy_n", 0) > 0:
            line += f"| {all_s['avg_buy']:>+7.1f}%"
        print(line)

    # ── Oracle 분석: 각 레짐에서 최적 전략 ──
    print(f"\n{'=' * 120}")
    print("  Oracle 분석 — 각 레짐에서 사후적 최적 전략")
    print("=" * 120)

    for regime in regimes:
        rows = by_regime.get(regime, [])
        if not rows:
            print(f"\n  [{regime}] 데이터 없음")
            continue

        best_strategy = None
        best_spread = -999

        for sname in ALL_STRATEGIES + ["auto"]:
            stats = compute_stats(rows, sname)
            if stats["spread"] > best_spread and stats["buy_n"] > 0:
                best_spread = stats["spread"]
                best_strategy = sname

        auto_spread = compute_stats(rows, "auto")["spread"]
        auto_name = REGIME_STRATEGY_MAP.get(regime, "v3")

        print(f"\n  [{regime}] ({len(rows)}건)")
        print(f"    Oracle 최적: {best_strategy} (스프레드 {best_spread:+.1f}%p)")
        print(f"    Auto 선택:   {auto_name} (스프레드 {auto_spread:+.1f}%p)")
        gap = best_spread - auto_spread
        if gap <= 1.0:
            print(f"    → auto가 oracle에 근접 (gap {gap:.1f}%p)")
        else:
            print(f"    → auto 개선 여지 있음 (gap {gap:.1f}%p, {best_strategy}가 더 나음)")

    # ── Auto vs 고정 전략 비교 ──
    print(f"\n{'=' * 120}")
    print("  Auto(레짐 전환) vs 고정 전략 — 전체 성과 비교")
    print("=" * 120)

    results_sorted = []
    for sname in compare_strategies:
        s = strategy_regime_stats[sname].get("all", {})
        results_sorted.append((sname, s.get("spread", 0), s.get("avg_buy", 0),
                               s.get("win_rate", 0), s.get("buy_n", 0)))

    results_sorted.sort(key=lambda x: x[1], reverse=True)

    print(f"\n  {'순위':<6}{'전략':<18}{'스프레드':>10}{'BUY평균':>10}{'승률':>8}{'BUY수':>8}")
    print(f"  {'-' * 58}")
    for i, (name, spread, avg, wr, n) in enumerate(results_sorted, 1):
        marker = " ←" if name == "auto" else ""
        print(f"  {i:<6}{name:<18}{spread:>+9.1f}%p{avg:>+9.1f}%{wr:>7.0f}%{n:>7}{marker}")

    # ── 상세 출력 ──
    if args.detail:
        print(f"\n{'=' * 120}")
        print("  레짐별 종목 상세")
        print("=" * 120)

        for regime in regimes:
            rows = by_regime.get(regime, [])
            if not rows:
                continue
            print(f"\n  --- {regime} ({len(rows)}건) ---")
            rows_sorted = sorted(rows, key=lambda r: r["return_pct"], reverse=True)
            print(f"  {'Ticker':<12}{'날짜':>12}{'수익률':>8}  {'legacy':>8} {'v3':>8} {'v6':>8} {'auto':>8}")
            for r in rows_sorted:
                print(f"  {r['ticker']:<12}{r['signal_date']:>12}{r['return_pct']:>+7.1f}%"
                      f"  {r['signals'].get('legacy','?'):>8} {r['signals'].get('v3','?'):>8}"
                      f"  {r['signals'].get('v6','?'):>8} {r['signals'].get('auto','?'):>8}")


if __name__ == "__main__":
    main()
