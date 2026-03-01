"""탐험 결과 포맷터.

fin-advisor의 router.py 패턴을 계승.
Markdown 리포트 및 터미널 출력 생성.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from src.agents.models import ExplorationResult, Signal, Urgency

# 신호별 이모지 (터미널/마크다운 공통)
SIGNAL_EMOJI = {
    Signal.STRONG_BUY: "⬆⬆ 강력매수",
    Signal.BUY: "⬆ 매수검토",
    Signal.WATCH: "➡ 관심종목",
    Signal.PASS: "⬇ 패스",
    Signal.AVOID: "⬇⬇ 회피",
}

URGENCY_LABEL = {
    Urgency.UNANIMOUS: "만장일치",
    Urgency.MAJORITY: "다수결",
    Urgency.SPLIT: "의견분열",
    Urgency.RED_FLAG: "⚠️ 리스크 거부권",
}


def format_markdown(result: ExplorationResult) -> str:
    """ExplorationResult를 Markdown 리포트로 변환한다."""
    lines = [
        f"# 종목 탐험 리포트: {result.ticker} ({result.company_name})",
        f"> 분석 시각: {result.timestamp}",
        "",
        "## 최종 판정",
        f"**{SIGNAL_EMOJI.get(result.final_signal, result.final_signal.value)}** "
        f"| 신뢰도 **{result.final_confidence*100:.0f}%** "
        f"| 합의 유형: **{URGENCY_LABEL.get(result.urgency, result.urgency.value)}**",
        "",
        "### 투표 집계",
    ]

    tally = result.vote_tally
    lines.append(
        f"- 긍정 {tally.get('positive', 0)}표 / "
        f"중립 {tally.get('neutral', 0)}표 / "
        f"부정 {tally.get('negative', 0)}표"
    )

    lines += [
        "",
        "## 에이전트별 의견",
    ]

    for op in result.opinions:
        sig = SIGNAL_EMOJI.get(op.signal, op.signal.value)
        lines.append(f"### {op.agent_name} — {sig} (신뢰도 {op.confidence*100:.0f}%)")
        lines.append(f"> {op.rationale}")

        if op.key_metrics:
            lines.append("")
            lines.append("**핵심 지표:**")
            for k, v in op.key_metrics.items():
                lines.append(f"- `{k}`: {v}")

        if op.strengths:
            lines.append("")
            lines.append("**강점:**")
            for s in op.strengths:
                lines.append(f"- {s}")

        if op.risk_flags:
            lines.append("")
            lines.append("**리스크:**")
            for r in op.risk_flags:
                lines.append(f"- ⚠️ {r}")

        lines.append("")

    if result.rebuttals:
        lines += ["## 교차 반박", ""]
        for rb in result.rebuttals:
            lines.append(f"**{rb.agent_name}** → *{rb.target_agent}*: {rb.argument}")
            lines.append("")

    if result.investment_thesis:
        lines += [
            "## 투자 thesis",
            result.investment_thesis,
            "",
        ]

    if result.key_risks:
        lines += ["## 핵심 리스크", ""]
        for r in result.key_risks:
            lines.append(f"- {r}")
        lines.append("")

    if result.entry_conditions:
        lines += ["## 진입 조건", ""]
        for c in result.entry_conditions:
            lines.append(f"- {c}")
        lines.append("")

    lines += [
        "---",
        "*면책조항: 본 리포트는 투자 참고용이며 투자 결정의 최종 책임은 투자자 본인에게 있습니다.*",
    ]

    return "\n".join(lines)


def format_terminal(result: ExplorationResult) -> str:
    """터미널 출력용 간략 요약."""
    sig_label = SIGNAL_EMOJI.get(result.final_signal, result.final_signal.value)
    urgency_label = URGENCY_LABEL.get(result.urgency, result.urgency.value)

    lines = [
        "=" * 60,
        f"  {result.ticker} — {result.company_name}",
        "=" * 60,
        f"  최종: {sig_label}  |  신뢰도: {result.final_confidence*100:.0f}%  |  {urgency_label}",
        "",
    ]

    tally = result.vote_tally
    lines.append(
        f"  투표: 긍정 {tally.get('positive', 0)} / "
        f"중립 {tally.get('neutral', 0)} / "
        f"부정 {tally.get('negative', 0)}"
    )
    lines.append("")

    for op in result.opinions:
        sig = SIGNAL_EMOJI.get(op.signal, op.signal.value)
        lines.append(f"  [{op.agent_name}] {sig} ({op.confidence*100:.0f}%)")
        lines.append(f"    {op.rationale}")

    if result.key_risks:
        lines.append("")
        lines.append("  [리스크]")
        for r in result.key_risks[:3]:
            lines.append(f"    ⚠️ {r}")

    if result.entry_conditions:
        lines.append("")
        lines.append("  [진입 조건]")
        for c in result.entry_conditions[:2]:
            lines.append(f"    → {c}")

    lines.append("=" * 60)
    return "\n".join(lines)


def save_journal(
    result: ExplorationResult,
    output_dir: str | Path = "data/journals",
) -> Path:
    """결과를 Markdown 파일로 저장한다.

    fin-advisor의 router.py journal 저장 패턴을 계승.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.date.today().isoformat()
    filename = f"{date_str}_explore_{result.ticker.replace('/', '-')}.md"
    filepath = output_dir / filename

    content = format_markdown(result)
    filepath.write_text(content, encoding="utf-8")

    return filepath
