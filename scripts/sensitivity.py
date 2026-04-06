#!/usr/bin/env python3
"""Phase 4: 파라미터 감도 분석.

Phase 1 캐시의 에이전트 의견을 재사용하여, 핵심 파라미터를 그리드 서치로
변경하며 스프레드/승률 최적점을 탐색한다. API 호출 없음.

Usage:
    python scripts/sensitivity.py                # 기본 그리드 서치
    python scripts/sensitivity.py --top 10       # 상위 10개 조합만 출력
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.models import AgentOpinion, Signal
from src.agents.signal_strategy import (
    STRATEGIES,
    StrategyParams,
    apply_strategy,
    _legacy_signal,
    get_strategy,
)

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "backtest_cache"
POSITIVE = {"strong_buy", "buy"}


def load_all_cached() -> list[dict]:
    """Phase 1 캐시를 전부 로드한다."""
    results = []
    for f in sorted(CACHE_DIR.glob("*.json")):
        with open(f) as fp:
            data = json.load(fp)
        if data.get("return_pct") is None:
            continue
        opinions = []
        for o in data["opinions"]:
            opinions.append(AgentOpinion(
                agent_name=o["agent"], signal=Signal(o["signal"]),
                confidence=o["confidence"], rationale="",
                risk_flags=o.get("risk_flags", []), strengths=o.get("strengths", []),
            ))
        results.append({
            "ticker": data["ticker"],
            "regime": data.get("regime", "neutral"),
            "return_pct": data["return_pct"],
            "opinions": opinions,
        })
    return results


def evaluate_params(data: list[dict], params: StrategyParams) -> dict:
    """파라미터 조합으로 전 데이터를 평가하고 성과를 반환한다."""
    buy_returns = []
    non_buy_returns = []

    for row in data:
        sig, _ = apply_strategy(params, row["opinions"], macro_regime=row["regime"])
        if sig.value in POSITIVE:
            buy_returns.append(row["return_pct"])
        else:
            non_buy_returns.append(row["return_pct"])

    total = len(data)
    buy_n = len(buy_returns)
    buy_ratio = buy_n / total * 100 if total else 0
    avg_buy = sum(buy_returns) / buy_n if buy_returns else 0
    avg_non = sum(non_buy_returns) / len(non_buy_returns) if non_buy_returns else 0
    spread = avg_buy - avg_non if non_buy_returns else 0
    win = sum(1 for r in buy_returns if r > 0)
    win_rate = win / buy_n * 100 if buy_n else 0

    return {
        "buy_n": buy_n, "buy_ratio": buy_ratio,
        "avg_buy": avg_buy, "spread": spread,
        "win": win, "win_rate": win_rate,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 4: 파라미터 감도 분석")
    parser.add_argument("--top", type=int, default=15, help="상위 N개 조합 출력")
    args = parser.parse_args()

    data = load_all_cached()
    print(f"캐시 로드: {len(data)}건\n")

    # ── 그리드 정의 ──
    val_sb_confs = [0.0, 0.40, 0.50, 0.60]          # val → SB 차단 conf
    val_buy_confs = [0.0, 0.55, 0.65, 0.75, 0.85]   # val → BUY 차단 conf
    mom_confs = [0.0, 0.45, 0.55, 0.65]              # mom → BUY 차단 conf
    min_pos_buys = [2, 3]                             # BUY 최소 투표
    min_pos_sbs = [3, 4]                              # SB 최소 투표
    growth_exempts = [True, False]                    # growth SB 면제

    total_combos = (len(val_sb_confs) * len(val_buy_confs) * len(mom_confs)
                    * len(min_pos_buys) * len(min_pos_sbs) * len(growth_exempts))
    print(f"그리드 크기: {total_combos}개 조합")

    # ── V3 기준선 ──
    v3_stats = evaluate_params(data, STRATEGIES["v3"])
    legacy_opinions_signals = []
    for row in data:
        sig = _legacy_signal(row["opinions"])
        if sig.value in POSITIVE:
            legacy_opinions_signals.append(row["return_pct"])
    legacy_buy_avg = sum(legacy_opinions_signals) / len(legacy_opinions_signals) if legacy_opinions_signals else 0

    print(f"\n기준선:")
    print(f"  V3:     spread {v3_stats['spread']:>+6.1f}%p | BUY {v3_stats['buy_n']:>3}개({v3_stats['buy_ratio']:.0f}%) | 승률 {v3_stats['win_rate']:.0f}%")
    print(f"  Legacy: BUY 평균 {legacy_buy_avg:+.1f}%")

    # ── 그리드 서치 ──
    results = []
    done = 0

    for vsb in val_sb_confs:
        for vb in val_buy_confs:
            for mc in mom_confs:
                for mpb in min_pos_buys:
                    for mps in min_pos_sbs:
                        for ge in growth_exempts:
                            done += 1
                            if done % 100 == 0:
                                print(f"\r  진행: {done}/{total_combos}", end="", flush=True)

                            params = StrategyParams(
                                name=f"grid_{done}",
                                description="",
                                risk_veto_only=True,
                                min_positive_for_buy=mpb,
                                min_positive_for_strong_buy=mps,
                                val_block_sb_conf=vsb,
                                val_block_buy_conf=vb,
                                growth_sb_exempts_val=ge,
                                momentum_block_conf=mc,
                            )
                            stats = evaluate_params(data, params)

                            # BUY가 0이면 스킵
                            if stats["buy_n"] == 0:
                                continue
                            # BUY 비율 10~70% 범위만
                            if stats["buy_ratio"] < 10 or stats["buy_ratio"] > 70:
                                continue

                            results.append({
                                "val_sb": vsb, "val_buy": vb, "mom": mc,
                                "min_buy": mpb, "min_sb": mps, "growth_ex": ge,
                                **stats,
                            })

    print(f"\r  완료: {done}/{total_combos} → 유효 {len(results)}개 조합\n")

    # ── 스프레드 기준 정렬 ──
    results.sort(key=lambda x: x["spread"], reverse=True)

    print(f"{'=' * 130}")
    print(f"  상위 {args.top}개 조합 (스프레드 기준)")
    print(f"{'=' * 130}")
    print(f"  {'#':<4} {'val_sb':>6} {'val_buy':>7} {'mom':>5} {'min_b':>5} {'min_sb':>6} {'gr_ex':>5}"
          f" | {'spread':>9} {'BUY수':>6} {'비율':>5} {'승률':>5} {'BUY평균':>8}")
    print(f"  {'-' * 120}")

    for i, r in enumerate(results[:args.top], 1):
        ge_str = "Y" if r["growth_ex"] else "N"
        is_v3 = (r["val_sb"] == 0.50 and r["val_buy"] == 0.65 and r["mom"] == 0.55
                 and r["min_buy"] == 3 and r["min_sb"] == 4 and r["growth_ex"])
        marker = " ← V3" if is_v3 else ""
        print(f"  {i:<4} {r['val_sb']:>6.2f} {r['val_buy']:>7.2f} {r['mom']:>5.2f}"
              f" {r['min_buy']:>5} {r['min_sb']:>6} {ge_str:>5}"
              f" | {r['spread']:>+8.1f}%p {r['buy_n']:>5}개 {r['buy_ratio']:>4.0f}% {r['win_rate']:>4.0f}%"
              f" {r['avg_buy']:>+7.1f}%{marker}")

    # ── 승률 기준 상위 ──
    results_by_wr = sorted(results, key=lambda x: x["win_rate"], reverse=True)
    print(f"\n{'=' * 130}")
    print(f"  상위 {args.top}개 조합 (승률 기준)")
    print(f"{'=' * 130}")
    print(f"  {'#':<4} {'val_sb':>6} {'val_buy':>7} {'mom':>5} {'min_b':>5} {'min_sb':>6} {'gr_ex':>5}"
          f" | {'spread':>9} {'BUY수':>6} {'비율':>5} {'승률':>5} {'BUY평균':>8}")
    print(f"  {'-' * 120}")

    for i, r in enumerate(results_by_wr[:args.top], 1):
        ge_str = "Y" if r["growth_ex"] else "N"
        print(f"  {i:<4} {r['val_sb']:>6.2f} {r['val_buy']:>7.2f} {r['mom']:>5.2f}"
              f" {r['min_buy']:>5} {r['min_sb']:>6} {ge_str:>5}"
              f" | {r['spread']:>+8.1f}%p {r['buy_n']:>5}개 {r['buy_ratio']:>4.0f}% {r['win_rate']:>4.0f}%"
              f" {r['avg_buy']:>+7.1f}%")

    # ── 개별 파라미터 감도 ──
    print(f"\n{'=' * 130}")
    print(f"  개별 파라미터 감도 (다른 파라미터 V3 고정, 1개만 변경)")
    print(f"{'=' * 130}")

    v3_base = STRATEGIES["v3"]
    param_sweeps = [
        ("val_block_sb_conf", [0.0, 0.40, 0.50, 0.60, 0.70]),
        ("val_block_buy_conf", [0.0, 0.50, 0.55, 0.65, 0.75, 0.85]),
        ("momentum_block_conf", [0.0, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65]),
        ("min_positive_for_buy", [2, 3, 4]),
        ("min_positive_for_strong_buy", [3, 4, 5]),
    ]

    for param_name, values in param_sweeps:
        print(f"\n  {param_name}:")
        print(f"    {'값':>8} {'spread':>9} {'BUY수':>6} {'비율':>5} {'승률':>5}")
        for val in values:
            params = replace(v3_base, **{param_name: val, "name": f"sweep_{param_name}_{val}"})
            stats = evaluate_params(data, params)
            is_default = (val == getattr(v3_base, param_name))
            marker = " ← V3" if is_default else ""
            print(f"    {val:>8} {stats['spread']:>+8.1f}%p {stats['buy_n']:>5}개 {stats['buy_ratio']:>4.0f}%"
                  f" {stats['win_rate']:>4.0f}%{marker}")

    # ── 오버피팅 경고 ──
    print(f"\n{'=' * 130}")
    print(f"  오버피팅 검증")
    print(f"{'=' * 130}")
    n_params = 6
    n_data = len(data)
    ratio = n_data / n_params
    print(f"  데이터: {n_data}건 | 파라미터: {n_params}개 | 비율: {ratio:.0f}:1")
    if ratio < 20:
        print(f"  ⚠ 비율 {ratio:.0f}:1 < 20:1 — 오버피팅 위험 높음. 결과를 참고용으로만 활용.")
    elif ratio < 50:
        print(f"  △ 비율 {ratio:.0f}:1 — 중간. 상위 조합의 방향성은 참고 가능하나 절대값 신뢰 제한.")
    else:
        print(f"  ✓ 비율 {ratio:.0f}:1 — 양호. 결과 신뢰도 적정.")


if __name__ == "__main__":
    main()
