#!/usr/bin/env python3
"""복수 시나리오 시뮬레이션 — 기존 저널 데이터 기반.

시나리오별 투표 규칙을 적용하여 승률/수익률/스프레드를 비교한다.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

# ── 저널 파싱 (simulate_new_rules.py 동일) ────────────────────────────────────

SIG_MAP_KR = {"강력매수": "STRONG_BUY", "매수검토": "BUY", "관심종목": "WATCH", "패스": "PASS", "회피": "AVOID"}
SIG_MAP_EMOJI = {"⬆⬆": "STRONG_BUY", "⬆": "BUY", "➡": "WATCH", "⬇": "PASS", "⬇⬇": "AVOID"}
POSITIVE = {"STRONG_BUY", "BUY"}
NEGATIVE = {"PASS", "AVOID"}


@dataclass
class AgentVote:
    agent: str
    signal: str
    confidence: float


@dataclass
class Exploration:
    ticker: str
    date: str
    final_signal: str
    final_confidence: int
    agents: list[AgentVote] = field(default_factory=list)


def parse_journals() -> list[Exploration]:
    journals_dir = "data/journals"
    files = sorted(glob.glob(f"{journals_dir}/*.md"))
    latest: dict[str, tuple[str, str]] = {}
    for f in files:
        m = re.match(r"(\d{4}-\d{2}-\d{2})_explore_(.+)\.md", os.path.basename(f))
        if m:
            date, ticker = m.group(1), m.group(2)
            if ticker not in latest or date > latest[ticker][0]:
                latest[ticker] = (date, f)

    results = []
    for ticker, (date, fpath) in sorted(latest.items()):
        with open(fpath) as f:
            content = f.read()
        final_signal = "UNKNOWN"
        for kr, en in SIG_MAP_KR.items():
            if kr in content[:400]:
                final_signal = en
                break
        conf_m = re.search(r"신뢰도\s*\*\*(\d+)%\*\*", content[:400])
        final_conf = int(conf_m.group(1)) if conf_m else 0
        agents = []
        for am in re.finditer(r"### (\S+)\s*—\s*(\S+)\s+(\S+)\s*\(신뢰도\s*(\d+)%\)", content):
            sig = SIG_MAP_EMOJI.get(am.group(2), SIG_MAP_KR.get(am.group(3), "UNKNOWN"))
            agents.append(AgentVote(agent=am.group(1), signal=sig, confidence=int(am.group(4)) / 100))
        if len(agents) >= 4:
            results.append(Exploration(ticker=ticker, date=date, final_signal=final_signal,
                                       final_confidence=final_conf, agents=agents))
    return results


def fetch_prices(explorations: list[Exploration]) -> dict[str, float | None]:
    print("가격 수집 중...")
    prices = {}
    for exp in explorations:
        key = f"{exp.ticker}|{exp.date}"
        if key in prices:
            continue
        try:
            t = yf.Ticker(exp.ticker)
            dt = datetime.strptime(exp.date, "%Y-%m-%d")
            hist = t.history(start=(dt - timedelta(days=3)).strftime("%Y-%m-%d"),
                             end=(dt + timedelta(days=2)).strftime("%Y-%m-%d"))
            if hist is None or hist.empty:
                prices[key] = None; continue
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
            mask = hist.index <= pd.Timestamp(dt + timedelta(days=1))
            ep = float(hist.loc[mask, "Close"].iloc[-1]) if mask.any() else float(hist["Close"].iloc[0])
            cur = t.history(period="5d")
            if cur is None or cur.empty:
                prices[key] = None; continue
            if isinstance(cur.columns, pd.MultiIndex):
                cur.columns = cur.columns.get_level_values(0)
            cp = float(cur["Close"].iloc[-1])
            prices[key] = (cp - ep) / ep * 100
        except Exception:
            prices[key] = None
    return prices


# ── 시나리오 정의 ─────────────────────────────────────────────────────────────

def scenario_baseline(exp: Exploration) -> str:
    """기존 규칙 그대로."""
    return exp.final_signal


def _get_agents(exp):
    risk = next((a for a in exp.agents if a.agent == "risk-analyst"), None)
    val = next((a for a in exp.agents if a.agent == "valuation-analyst"), None)
    mom = next((a for a in exp.agents if a.agent == "momentum-analyst"), None)
    growth = next((a for a in exp.agents if a.agent == "growth-analyst"), None)
    voters = [a for a in exp.agents if a.agent != "risk-analyst"]
    pos = sum(1 for a in voters if a.signal in POSITIVE)
    neg = sum(1 for a in voters if a.signal in NEGATIVE)
    return risk, val, mom, growth, voters, pos, neg


def _base_from_votes(pos, neg):
    if pos >= 4: return "STRONG_BUY"
    if pos >= 3: return "BUY"
    if neg >= 3: return "AVOID"
    if neg >= 2: return "PASS"
    return "WATCH"


def _apply_risk_veto(sig, risk):
    if not risk: return sig
    if risk.signal == "AVOID" and risk.confidence >= 0.85 and sig in POSITIVE:
        return "WATCH"
    if risk.signal == "AVOID" and risk.confidence >= 0.70 and sig == "STRONG_BUY":
        return "BUY"
    return sig


def scenario_v1(exp: Exploration) -> str:
    """V1: 최소합의 + risk 거부권전용 + val 강차단(0.65) + mom 필터."""
    risk, val, mom, growth, voters, pos, neg = _get_agents(exp)
    sig = _base_from_votes(pos, neg)
    sig = _apply_risk_veto(sig, risk)
    # val 차단
    if val and val.signal in NEGATIVE and val.confidence >= 0.50 and sig == "STRONG_BUY":
        sig = "BUY"
    if val and val.signal == "AVOID" and val.confidence >= 0.65 and sig == "BUY":
        sig = "WATCH"
    # mom 필터
    if mom and mom.signal in NEGATIVE and mom.confidence >= 0.55 and sig in POSITIVE:
        sig = "WATCH"
    return sig


def scenario_v2(exp: Exploration) -> str:
    """V2: V1 + val 강차단 완화(0.75)."""
    risk, val, mom, growth, voters, pos, neg = _get_agents(exp)
    sig = _base_from_votes(pos, neg)
    sig = _apply_risk_veto(sig, risk)
    if val and val.signal in NEGATIVE and val.confidence >= 0.50 and sig == "STRONG_BUY":
        sig = "BUY"
    if val and val.signal == "AVOID" and val.confidence >= 0.75 and sig == "BUY":
        sig = "WATCH"
    if mom and mom.signal in NEGATIVE and mom.confidence >= 0.55 and sig in POSITIVE:
        sig = "WATCH"
    return sig


def scenario_v3(exp: Exploration) -> str:
    """V3: V1 + growth SB이면 val 강차단 면제."""
    risk, val, mom, growth, voters, pos, neg = _get_agents(exp)
    sig = _base_from_votes(pos, neg)
    sig = _apply_risk_veto(sig, risk)
    growth_sb = growth and growth.signal == "STRONG_BUY"
    if val and val.signal in NEGATIVE and val.confidence >= 0.50 and sig == "STRONG_BUY":
        sig = "BUY"
    if val and val.signal == "AVOID" and val.confidence >= 0.65 and sig == "BUY":
        if not growth_sb:  # growth SB면 면제
            sig = "WATCH"
    if mom and mom.signal in NEGATIVE and mom.confidence >= 0.55 and sig in POSITIVE:
        sig = "WATCH"
    return sig


def scenario_v4(exp: Exploration) -> str:
    """V4: V2 + V3 결합 (val 0.75 완화 + growth SB 면제)."""
    risk, val, mom, growth, voters, pos, neg = _get_agents(exp)
    sig = _base_from_votes(pos, neg)
    sig = _apply_risk_veto(sig, risk)
    growth_sb = growth and growth.signal == "STRONG_BUY"
    if val and val.signal in NEGATIVE and val.confidence >= 0.50 and sig == "STRONG_BUY":
        sig = "BUY"
    if val and val.signal == "AVOID" and val.confidence >= 0.75 and sig == "BUY":
        if not growth_sb:
            sig = "WATCH"
    if mom and mom.signal in NEGATIVE and mom.confidence >= 0.55 and sig in POSITIVE:
        sig = "WATCH"
    return sig


def scenario_v5(exp: Exploration) -> str:
    """V5: V4 + 합의문턱 완화 (BUY 3+/5 유지, SB 4+/5 유지, val 0.75, growth 면제, mom 0.60)."""
    risk, val, mom, growth, voters, pos, neg = _get_agents(exp)
    sig = _base_from_votes(pos, neg)
    sig = _apply_risk_veto(sig, risk)
    growth_sb = growth and growth.signal == "STRONG_BUY"
    if val and val.signal in NEGATIVE and val.confidence >= 0.50 and sig == "STRONG_BUY":
        sig = "BUY"
    if val and val.signal == "AVOID" and val.confidence >= 0.75 and sig == "BUY":
        if not growth_sb:
            sig = "WATCH"
    # mom 필터 완화 (0.60)
    if mom and mom.signal in NEGATIVE and mom.confidence >= 0.60 and sig in POSITIVE:
        sig = "WATCH"
    return sig


def scenario_v6(exp: Exploration) -> str:
    """V6: V4 + val 차단도 growth SB면 면제 (SB→BUY 차단 면제)."""
    risk, val, mom, growth, voters, pos, neg = _get_agents(exp)
    sig = _base_from_votes(pos, neg)
    sig = _apply_risk_veto(sig, risk)
    growth_sb = growth and growth.signal == "STRONG_BUY"
    if val and val.signal in NEGATIVE and val.confidence >= 0.50 and sig == "STRONG_BUY":
        if not growth_sb:
            sig = "BUY"
    if val and val.signal == "AVOID" and val.confidence >= 0.75 and sig == "BUY":
        if not growth_sb:
            sig = "WATCH"
    if mom and mom.signal in NEGATIVE and mom.confidence >= 0.55 and sig in POSITIVE:
        sig = "WATCH"
    return sig


def _apply_v3_core(exp: Exploration) -> str:
    """V3 코어 로직 (재사용용)."""
    risk, val, mom, growth, voters, pos, neg = _get_agents(exp)
    sig = _base_from_votes(pos, neg)
    sig = _apply_risk_veto(sig, risk)
    growth_sb = growth and growth.signal == "STRONG_BUY"
    if val and val.signal in NEGATIVE and val.confidence >= 0.50 and sig == "STRONG_BUY":
        sig = "BUY"
    if val and val.signal == "AVOID" and val.confidence >= 0.65 and sig == "BUY":
        if not growth_sb:
            sig = "WATCH"
    if mom and mom.signal in NEGATIVE and mom.confidence >= 0.55 and sig in POSITIVE:
        sig = "WATCH"
    return sig


# ── 매크로 레짐 판정 (탐험일 기준) ───────────────────────────────────────────

# 실측 매크로 레짐 (S&P500 vs SMA50 + VIX)
# 2026-03-07: S&P 6740 < SMA50 6902, VIX 29.5 → BEAR
# 2026-03-11: S&P 6776 < SMA50 6895, VIX 24.2 → NEUTRAL (VIX < 25)
# 2026-03-12: S&P 6673 < SMA50 6890, VIX 27.3 → BEAR
# 2026-03-13: S&P 6632 < SMA50 6885, VIX 27.2 → BEAR
# 2026-03-14: S&P 6632 < SMA50 6885, VIX 27.2 → BEAR
# 2026-03-16: S&P 6699 < SMA50 6881, VIX 23.5 → NEUTRAL (VIX < 25)
MACRO_REGIME_MAP: dict[str, str] = {
    "2026-03-02": "bear",
    "2026-03-03": "bear",
    "2026-03-04": "bear",
    "2026-03-05": "bear",
    "2026-03-06": "bear",
    "2026-03-07": "bear",
    "2026-03-09": "bear",
    "2026-03-10": "bear",
    "2026-03-11": "neutral",
    "2026-03-12": "bear",
    "2026-03-13": "bear",
    "2026-03-14": "bear",
    "2026-03-16": "neutral",
}
MACRO_VIX_MAP: dict[str, float] = {
    "2026-03-07": 29.5, "2026-03-11": 24.2, "2026-03-12": 27.3,
    "2026-03-13": 27.2, "2026-03-14": 27.2, "2026-03-16": 23.5,
}


def get_macro_regime(explore_date: str) -> str:
    return MACRO_REGIME_MAP.get(explore_date, "neutral")


def get_vix(explore_date: str) -> float:
    return MACRO_VIX_MAP.get(explore_date, 22.0)


# ── 매크로 게이트 시나리오 ────────────────────────────────────────────────────

def scenario_m1(exp: Exploration) -> str:
    """M1: V3 + bear → STRONG_BUY 차단 (최대 BUY)."""
    sig = _apply_v3_core(exp)
    regime = get_macro_regime(exp.date)
    if regime == "bear" and sig == "STRONG_BUY":
        sig = "BUY"
    return sig


def scenario_m2(exp: Exploration) -> str:
    """M2: V3 + bear → BUY 이상 전부 1단계 하향."""
    sig = _apply_v3_core(exp)
    regime = get_macro_regime(exp.date)
    if regime == "bear":
        if sig == "STRONG_BUY":
            sig = "BUY"
        elif sig == "BUY":
            sig = "WATCH"
    return sig


def scenario_m3(exp: Exploration) -> str:
    """M3: V3 + bear → 전체 WATCH 격하 (시스템 브레이크)."""
    sig = _apply_v3_core(exp)
    regime = get_macro_regime(exp.date)
    if regime == "bear" and sig in POSITIVE:
        sig = "WATCH"
    return sig


def scenario_m4(exp: Exploration) -> str:
    """M4: V3 + bear → SB차단 + VIX>28이면 BUY도 WATCH."""
    sig = _apply_v3_core(exp)
    regime = get_macro_regime(exp.date)
    vix = get_vix(exp.date)
    if regime == "bear":
        if sig == "STRONG_BUY":
            sig = "BUY"
        if vix > 28 and sig == "BUY":
            sig = "WATCH"
    return sig


def scenario_m5(exp: Exploration) -> str:
    """M5: V3 + bear → 1단계 하향 + growth SB면 BUY 유지."""
    sig = _apply_v3_core(exp)
    regime = get_macro_regime(exp.date)
    _, _, _, growth, _, _, _ = _get_agents(exp)
    growth_sb = growth and growth.signal == "STRONG_BUY"
    if regime == "bear":
        if sig == "STRONG_BUY":
            sig = "BUY"
        elif sig == "BUY" and not growth_sb:
            sig = "WATCH"
    return sig


def scenario_m6(exp: Exploration) -> str:
    """M6: V3 + neutral/bear 구분. neutral → SB차단만, bear → 1단계 하향."""
    sig = _apply_v3_core(exp)
    regime = get_macro_regime(exp.date)
    if regime == "bear":
        if sig == "STRONG_BUY":
            sig = "BUY"
        elif sig == "BUY":
            sig = "WATCH"
    elif regime == "neutral":
        if sig == "STRONG_BUY":
            sig = "BUY"
    return sig


SCENARIOS = {
    "기존":               scenario_baseline,
    "V3(base)":          scenario_v3,
    "M1(bear→SB차단)":    scenario_m1,
    "M2(bear→1단계↓)":    scenario_m2,
    "M3(bear→전체WATCH)": scenario_m3,
    "M4(bear+VIX28)":    scenario_m4,
    "M5(bear+growth면제)": scenario_m5,
    "M6(neutral도SB차단)": scenario_m6,
}


# ── 메인 ──────────────────────────────────────────────────────────────────────

def compute_stats(results: list[dict], sig_key: str) -> dict:
    with_price = [r for r in results if r["change_pct"] is not None]
    buys = [r for r in with_price if r[sig_key] in POSITIVE]
    non_buys = [r for r in with_price if r[sig_key] not in POSITIVE]
    sbs = [r for r in with_price if r[sig_key] == "STRONG_BUY"]
    total = len(with_price)

    avg_buy = sum(r["change_pct"] for r in buys) / len(buys) if buys else 0
    win_buy = sum(1 for r in buys if r["change_pct"] > 0)
    avg_non = sum(r["change_pct"] for r in non_buys) / len(non_buys) if non_buys else 0
    avg_sb = sum(r["change_pct"] for r in sbs) / len(sbs) if sbs else 0
    spread = avg_buy - avg_non if non_buys else 0
    buy_ratio = len(buys) / total * 100 if total else 0
    win_rate = win_buy / len(buys) * 100 if buys else 0

    return {
        "buy_count": len(buys), "sb_count": len(sbs), "non_buy_count": len(non_buys),
        "buy_ratio": buy_ratio, "avg_buy": avg_buy, "avg_sb": avg_sb,
        "avg_non": avg_non, "spread": spread, "win_rate": win_rate, "win_buy": win_buy,
        "total": total,
    }


def main():
    explorations = parse_journals()
    print(f"파싱: {len(explorations)}개 종목\n")

    prices = fetch_prices(explorations)

    # 기본 결과 생성
    base_results = []
    for exp in explorations:
        chg = prices.get(f"{exp.ticker}|{exp.date}")
        row = {"ticker": exp.ticker, "date": exp.date, "change_pct": chg, "exp": exp}
        for name, fn in SCENARIOS.items():
            row[name] = fn(exp)
        base_results.append(row)

    # ── 시나리오별 통계 ──
    print("\n" + "=" * 120)
    print(f"{'시나리오':<20} {'BUY이상':>7} {'SB':>4} {'비율':>6} {'평균수익':>8} {'SB평균':>8} {'비매수':>8} {'스프레드':>8} {'승률':>12}")
    print("-" * 120)

    for name in SCENARIOS:
        s = compute_stats(base_results, name)
        print(
            f"{name:<20} {s['buy_count']:>5}개 {s['sb_count']:>3}개 "
            f"{s['buy_ratio']:>5.0f}% {s['avg_buy']:>+7.1f}% {s['avg_sb']:>+7.1f}% "
            f"{s['avg_non']:>+7.1f}% {s['spread']:>+7.1f}%p "
            f"{s['win_buy']:>2}/{s['buy_count']:<2} ({s['win_rate']:.0f}%)"
        )
    print("=" * 120)

    # ── 시나리오별 BUY 유지/변경된 종목 상세 (상위 시나리오만) ──
    best_name = max(SCENARIOS.keys(), key=lambda n: compute_stats(base_results, n)["spread"])
    print(f"\n=== 최적 시나리오: {best_name} — 상세 ===\n")

    # 신호 분포
    from collections import Counter
    dist = Counter(r[best_name] for r in base_results)
    print("신호 분포:")
    for sig in ["STRONG_BUY", "BUY", "WATCH", "PASS", "AVOID"]:
        old_n = sum(1 for r in base_results if r["기존"] == sig)
        new_n = dist.get(sig, 0)
        print(f"  {sig:<12}: {old_n:>2} → {new_n:>2}  ({new_n - old_n:+d})")

    # BUY 유지 종목
    kept = [r for r in base_results if r[best_name] in POSITIVE and r["change_pct"] is not None]
    kept.sort(key=lambda x: x["change_pct"], reverse=True)
    print(f"\nBUY 유지 {len(kept)}개:")
    for r in kept:
        print(f"  {r['ticker']:<12} {r[best_name]:<12} {r['change_pct']:+.1f}%")

    # 하향된 종목 중 상승한 것 (오탐)
    false_neg = [r for r in base_results if r["기존"] in POSITIVE and r[best_name] not in POSITIVE
                 and r["change_pct"] is not None and r["change_pct"] > 2.0]
    if false_neg:
        false_neg.sort(key=lambda x: x["change_pct"], reverse=True)
        print(f"\n⚠ 하향했으나 +2%+ 상승 (오탐 {len(false_neg)}개):")
        for r in false_neg:
            print(f"  {r['ticker']:<12} {r['기존']:<12} → {r[best_name]:<12} {r['change_pct']:+.1f}%")

    # 하향된 종목 중 하락한 것 (정탐)
    true_neg = [r for r in base_results if r["기존"] in POSITIVE and r[best_name] not in POSITIVE
                and r["change_pct"] is not None and r["change_pct"] < 0]
    if true_neg:
        print(f"\n✓ 하향 + 실제 하락 (정탐 {len(true_neg)}개):")
        for r in sorted(true_neg, key=lambda x: x["change_pct"]):
            print(f"  {r['ticker']:<12} {r['기존']:<12} → {r[best_name]:<12} {r['change_pct']:+.1f}%")


if __name__ == "__main__":
    main()
