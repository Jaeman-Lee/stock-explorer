#!/usr/bin/env python3
"""기존 저널 데이터로 새 투표 규칙을 시뮬레이션한다.

기존 에이전트별 의견을 파싱 → 5가지 개선안을 적용 → 기존 vs 신규 신호 비교.
실제 가격 변동과 대조하여 승률/수익률을 산출한다.

Usage:
    python scripts/simulate_new_rules.py
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf


# ── 저널 파싱 ────────────────────────────────────────────────────────────────

SIG_MAP_KR = {
    "강력매수": "STRONG_BUY",
    "매수검토": "BUY",
    "관심종목": "WATCH",
    "패스": "PASS",
    "회피": "AVOID",
}

SIG_MAP_EMOJI = {
    "⬆⬆": "STRONG_BUY",
    "⬆": "BUY",
    "➡": "WATCH",
    "⬇": "PASS",
    "⬇⬇": "AVOID",
}


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


def parse_journal(filepath: str) -> Exploration | None:
    """저널 파일에서 최종 신호 + 에이전트별 의견을 파싱한다."""
    with open(filepath) as f:
        content = f.read()

    basename = os.path.basename(filepath)
    m = re.match(r"(\d{4}-\d{2}-\d{2})_explore_(.+)\.md", basename)
    if not m:
        return None
    date, ticker = m.group(1), m.group(2)

    # 최종 신호
    final_signal = "UNKNOWN"
    for kr, en in SIG_MAP_KR.items():
        if kr in content[:400]:
            final_signal = en
            break

    # 최종 신뢰도
    conf_m = re.search(r"신뢰도\s*\*\*(\d+)%\*\*", content[:400])
    final_conf = int(conf_m.group(1)) if conf_m else 0

    # 에이전트별 의견 파싱
    agents = []
    for am in re.finditer(
        r"### (\S+)\s*—\s*(\S+)\s+(\S+)\s*\(신뢰도\s*(\d+)%\)", content
    ):
        agent_name = am.group(1)
        emoji = am.group(2)
        signal = SIG_MAP_EMOJI.get(emoji, SIG_MAP_KR.get(am.group(3), "UNKNOWN"))
        conf = int(am.group(4))
        agents.append(AgentVote(agent=agent_name, signal=signal, confidence=conf / 100))

    return Exploration(
        ticker=ticker,
        date=date,
        final_signal=final_signal,
        final_confidence=final_conf,
        agents=agents,
    )


# ── 새 규칙 시뮬레이터 ───────────────────────────────────────────────────────

POSITIVE = {"STRONG_BUY", "BUY"}
NEGATIVE = {"PASS", "AVOID"}


def simulate_new_signal(exp: Exploration) -> tuple[str, str]:
    """개선안 5가지를 적용하여 새 최종 신호를 산출한다.

    Returns:
        (new_signal, reason)
    """
    if len(exp.agents) < 4:
        return exp.final_signal, "에이전트 부족"

    # 에이전트 분류
    risk = next((a for a in exp.agents if a.agent == "risk-analyst"), None)
    valuation = next((a for a in exp.agents if a.agent == "valuation-analyst"), None)
    momentum = next((a for a in exp.agents if a.agent == "momentum-analyst"), None)

    # 투표 에이전트 = risk 제외 (개선안 2: risk는 거부권 전용)
    voters = [a for a in exp.agents if a.agent != "risk-analyst"]
    positive_votes = sum(1 for a in voters if a.signal in POSITIVE)
    negative_votes = sum(1 for a in voters if a.signal in NEGATIVE)
    total_voters = len(voters)

    # ── 개선안 1: 최소 합의 문턱 ──
    # STRONG_BUY: 4+/5 긍정, BUY: 3+/5 긍정
    if positive_votes >= 4:
        base_signal = "STRONG_BUY"
    elif positive_votes >= 3:
        base_signal = "BUY"
    elif positive_votes >= 2:
        base_signal = "WATCH"
    elif negative_votes >= 3:
        base_signal = "AVOID"
    elif negative_votes >= 2:
        base_signal = "PASS"
    else:
        base_signal = "WATCH"

    reason_parts = [f"투표 {positive_votes}/{total_voters} 긍정"]

    # ── 개선안 2: risk 거부권 (기존 유지, 투표에서만 제외) ──
    if risk and risk.signal == "AVOID" and risk.confidence >= 0.85:
        if base_signal in POSITIVE:
            base_signal = "WATCH"
            reason_parts.append("risk 하드거부")
    elif risk and risk.signal == "AVOID" and risk.confidence >= 0.70:
        if base_signal == "STRONG_BUY":
            base_signal = "BUY"
            reason_parts.append("risk 소프트거부")

    # ── 개선안 4: valuation 차단 ──
    # valuation PASS/AVOID(conf≥0.50) → STRONG_BUY 차단
    if valuation and valuation.signal in NEGATIVE and valuation.confidence >= 0.50:
        if base_signal == "STRONG_BUY":
            base_signal = "BUY"
            reason_parts.append("val 차단→BUY")
        # valuation AVOID(conf≥0.65) → BUY도 차단
        if valuation.signal == "AVOID" and valuation.confidence >= 0.65:
            if base_signal == "BUY":
                base_signal = "WATCH"
                reason_parts.append("val 강차단→WATCH")

    # ── 개선안 3: 모멘텀 하락 필터 (momentum PASS/AVOID → BUY 차단) ──
    if momentum and momentum.signal in NEGATIVE and momentum.confidence >= 0.55:
        if base_signal in POSITIVE:
            base_signal = "WATCH"
            reason_parts.append("momentum 하락")

    return base_signal, " | ".join(reason_parts)


# ── 가격 수집 ─────────────────────────────────────────────────────────────────

def fetch_price_change(ticker: str, explore_date: str) -> float | None:
    """탐험일 → 최근 종가 등락률을 계산한다."""
    try:
        t = yf.Ticker(ticker)
        dt = datetime.strptime(explore_date, "%Y-%m-%d")
        start = dt - timedelta(days=3)
        end = dt + timedelta(days=2)

        hist = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if hist is None or hist.empty:
            return None
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)

        hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
        mask = hist.index <= pd.Timestamp(dt + timedelta(days=1))
        explore_price = float(hist.loc[mask, "Close"].iloc[-1]) if mask.any() else float(hist["Close"].iloc[0])

        cur = t.history(period="5d")
        if cur is None or cur.empty:
            return None
        if isinstance(cur.columns, pd.MultiIndex):
            cur.columns = cur.columns.get_level_values(0)
        current_price = float(cur["Close"].iloc[-1])

        return (current_price - explore_price) / explore_price * 100
    except Exception:
        return None


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    journals_dir = "data/journals"
    files = sorted(glob.glob(f"{journals_dir}/*.md"))

    # 종목별 최신 저널만
    latest: dict[str, str] = {}
    for f in files:
        base = os.path.basename(f)
        m = re.match(r"(\d{4}-\d{2}-\d{2})_explore_(.+)\.md", base)
        if m:
            date, ticker = m.group(1), m.group(2)
            if ticker not in latest or date > latest[ticker]:
                latest[ticker] = date

    # 파싱
    explorations: list[Exploration] = []
    for ticker, date in sorted(latest.items()):
        fpath = f"{journals_dir}/{date}_explore_{ticker}.md"
        exp = parse_journal(fpath)
        if exp and len(exp.agents) >= 4:
            explorations.append(exp)

    print(f"파싱 완료: {len(explorations)}개 종목\n")

    # 시뮬레이션
    print("가격 데이터 수집 중...")
    results = []
    for exp in explorations:
        new_signal, reason = simulate_new_signal(exp)
        chg = fetch_price_change(exp.ticker, exp.date)
        results.append({
            "ticker": exp.ticker,
            "date": exp.date,
            "old_signal": exp.final_signal,
            "old_conf": exp.final_confidence,
            "new_signal": new_signal,
            "reason": reason,
            "change_pct": chg,
        })

    # ── 결과 출력 ──
    print("\n" + "=" * 110)
    print(f"{'Ticker':<12} {'날짜':>10} {'기존신호':<12} {'새신호':<12} {'등락률':>8}  {'변경 사유'}")
    print("-" * 110)

    # 신호가 변경된 종목 먼저
    changed = [r for r in results if r["old_signal"] != r["new_signal"]]
    unchanged = [r for r in results if r["old_signal"] == r["new_signal"]]

    for r in sorted(changed, key=lambda x: x.get("change_pct") or -999, reverse=True):
        chg = f"{r['change_pct']:+.1f}%" if r["change_pct"] is not None else "N/A"
        marker = "→" if r["old_signal"] != r["new_signal"] else " "
        print(f"{r['ticker']:<12} {r['date']:>10} {r['old_signal']:<12} {marker}{r['new_signal']:<11} {chg:>8}  {r['reason']}")

    print("-" * 110)
    for r in sorted(unchanged, key=lambda x: x.get("change_pct") or -999, reverse=True):
        chg = f"{r['change_pct']:+.1f}%" if r["change_pct"] is not None else "N/A"
        print(f"{r['ticker']:<12} {r['date']:>10} {r['old_signal']:<12}  {r['new_signal']:<11} {chg:>8}  {r['reason']}")

    # ── 통계 ──
    print("\n" + "=" * 80)
    print("=== 기존 규칙 vs 새 규칙 비교 ===\n")

    for label, signal_set in [("기존", "old_signal"), ("새규칙", "new_signal")]:
        buys = [r for r in results if r[signal_set] in POSITIVE and r["change_pct"] is not None]
        non_buys = [r for r in results if r[signal_set] not in POSITIVE and r["change_pct"] is not None]

        if buys:
            avg_buy = sum(r["change_pct"] for r in buys) / len(buys)
            win_buy = sum(1 for r in buys if r["change_pct"] > 0)
        else:
            avg_buy, win_buy = 0, 0

        if non_buys:
            avg_non = sum(r["change_pct"] for r in non_buys) / len(non_buys)
        else:
            avg_non = 0

        spread = avg_buy - avg_non if non_buys else 0
        total_with_price = len([r for r in results if r["change_pct"] is not None])
        buy_ratio = len(buys) / total_with_price * 100 if total_with_price else 0

        sb = [r for r in results if r[signal_set] == "STRONG_BUY" and r["change_pct"] is not None]
        avg_sb = sum(r["change_pct"] for r in sb) / len(sb) if sb else 0

        print(f"[{label}]")
        print(f"  BUY이상: {len(buys)}개 ({buy_ratio:.0f}%) | 평균 {avg_buy:+.1f}% | 승률 {win_buy}/{len(buys)} ({win_buy/len(buys)*100:.0f}%)" if buys else f"  BUY이상: 0개")
        print(f"  STRONG_BUY: {len(sb)}개 | 평균 {avg_sb:+.1f}%")
        print(f"  비매수: {len(non_buys)}개 | 평균 {avg_non:+.1f}%")
        print(f"  스프레드(BUY - 비매수): {spread:+.1f}%p")
        print()

    # 신호 분포 비교
    print("=== 신호 분포 비교 ===\n")
    for sig in ["STRONG_BUY", "BUY", "WATCH", "PASS", "AVOID"]:
        old_n = sum(1 for r in results if r["old_signal"] == sig)
        new_n = sum(1 for r in results if r["new_signal"] == sig)
        print(f"  {sig:<12}: {old_n:>2} → {new_n:>2}  ({new_n - old_n:+d})")

    # 신호 변경으로 인한 효과
    print("\n=== 신호 변경 효과 분석 ===\n")
    downgraded = [r for r in results if r["old_signal"] in POSITIVE and r["new_signal"] not in POSITIVE and r["change_pct"] is not None]
    if downgraded:
        avg_down = sum(r["change_pct"] for r in downgraded) / len(downgraded)
        print(f"  BUY→WATCH/PASS로 하향된 종목 {len(downgraded)}개: 실제 평균 {avg_down:+.1f}%")
        print(f"    → 하향이 정확했으면 음수, 틀렸으면 양수")
        for r in sorted(downgraded, key=lambda x: x["change_pct"]):
            chg = f"{r['change_pct']:+.1f}%"
            print(f"      {r['ticker']:<12} {r['old_signal']:>12} → {r['new_signal']:<12} {chg:>8}  {r['reason']}")

    kept = [r for r in results if r["old_signal"] in POSITIVE and r["new_signal"] in POSITIVE and r["change_pct"] is not None]
    if kept:
        avg_kept = sum(r["change_pct"] for r in kept) / len(kept)
        win_kept = sum(1 for r in kept if r["change_pct"] > 0)
        print(f"\n  BUY 유지된 종목 {len(kept)}개: 평균 {avg_kept:+.1f}% | 승률 {win_kept}/{len(kept)} ({win_kept/len(kept)*100:.0f}%)")


if __name__ == "__main__":
    main()
