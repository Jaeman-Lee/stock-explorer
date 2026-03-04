"""Telegram 메시지 전송 유틸리티.

fin-advisor의 telegram_sender.py 패턴을 계승.
ExplorationResult를 Telegram Markdown 형식으로 포맷하여 전송.
"""

from __future__ import annotations

import logging
import os

import requests

from src.agents.models import ExplorationResult, Signal, Urgency

log = logging.getLogger(__name__)

TELEGRAM_MAX_LEN = 4096

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


def _credentials() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def send_message(text: str, chat_id: str | None = None) -> bool:
    """단일 텍스트 메시지를 Telegram으로 전송한다."""
    token, default_chat_id = _credentials()
    target = chat_id or default_chat_id

    if not token or not target:
        log.error("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 미설정")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = _split(text)
    success = True

    for chunk in chunks:
        try:
            resp = requests.post(
                url,
                json={"chat_id": target, "text": chunk, "parse_mode": "Markdown"},
                timeout=15,
            )
            if resp.status_code != 200:
                log.error(f"Telegram API 오류: {resp.status_code} {resp.text}")
                success = False
        except requests.RequestException as e:
            log.error(f"Telegram 전송 실패: {e}")
            success = False

    return success


def send_exploration_result(result: ExplorationResult, chat_id: str | None = None) -> bool:
    """ExplorationResult를 Telegram으로 전송한다."""
    msg = _format_result(result)
    return send_message(msg, chat_id)


def send_scan_summary(results: list[ExplorationResult], chat_id: str | None = None) -> bool:
    """여러 종목 스캔 결과 요약을 한 번에 전송한다."""
    if not results:
        return send_message("스캔 결과 없음", chat_id)

    lines = [f"*종목 탐험 스캔 완료 — {len(results)}개 종목*", ""]

    for r in results:
        sig = SIGNAL_EMOJI.get(r.final_signal, r.final_signal.value)
        urgency = URGENCY_LABEL.get(r.urgency, r.urgency.value)
        lines.append(
            f"{sig} *{r.ticker}* ({r.company_name[:12]})\n"
            f"  신뢰도 {r.final_confidence*100:.0f}% | {urgency}"
        )

    lines += ["", "_※ 투자 결정의 책임은 본인에게 있습니다_"]
    return send_message("\n".join(lines), chat_id)


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _format_result(result: ExplorationResult) -> str:
    sig = SIGNAL_EMOJI.get(result.final_signal, result.final_signal.value)
    urgency = URGENCY_LABEL.get(result.urgency, result.urgency.value)
    tally = result.vote_tally

    lines = [
        f"*{result.ticker} — {result.company_name}*",
        f"*{sig}* | 신뢰도 {result.final_confidence*100:.0f}% | {urgency}",
        f"투표: 긍정 {tally.get('positive',0)} / 중립 {tally.get('neutral',0)} / 부정 {tally.get('negative',0)}",
        "",
    ]

    for op in result.opinions:
        op_sig = SIGNAL_EMOJI.get(op.signal, op.signal.value)
        lines.append(f"[{op.agent_name}] {op_sig} ({op.confidence*100:.0f}%)")
        lines.append(f"  {op.rationale}")

    if result.key_risks:
        lines += ["", "*핵심 리스크*"]
        for r in result.key_risks[:3]:
            lines.append(f"⚠️ {r}")

    if result.entry_conditions:
        lines += ["", "*진입 조건*"]
        for c in result.entry_conditions[:2]:
            lines.append(f"→ {c}")

    lines += ["", "_※ 투자 결정의 책임은 본인에게 있습니다_"]
    return "\n".join(lines)


def _split(text: str) -> list[str]:
    if len(text) <= TELEGRAM_MAX_LEN:
        return [text]
    chunks = []
    while text:
        if len(text) <= TELEGRAM_MAX_LEN:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, TELEGRAM_MAX_LEN)
        if split_at == -1:
            split_at = TELEGRAM_MAX_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
