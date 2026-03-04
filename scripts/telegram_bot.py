#!/usr/bin/env python3
"""stock-explorer Telegram 양방향 봇 — Long Polling.

지원 명령어:
  /explore TICKER  — 종목 풀 탐험 (6에이전트 토론)
  탐험 TICKER      — 위와 동일 (한국어)
  /top             — 오늘 BUY+ 종목 요약
  탑픽             — 위와 동일 (한국어)
  /scan TICKER     — 빠른 가격·RSI·MACD 스냅샷
  스캔 TICKER      — 위와 동일 (한국어)
  /help / 도움말   — 명령어 목록

보안: TELEGRAM_CHAT_ID와 일치하는 chat_id만 처리.

실행:
  TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python scripts/telegram_bot.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 프로젝트 루트 추가
_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_root))

# .env 자동 로드
_env = _root / ".env"
if _env.exists():
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                line = line.removeprefix("export ")
                key, _, val = line.partition("=")
                if key and val:
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

import requests
import yfinance as yf
import pandas as pd

from src.agents.models import Signal
from src.agents.moderator import ExplorationModerator
from src.pipeline.context_builder import build_context
from src.telegram.sender import send_message, send_exploration_result
from src.utils.config import JOURNALS_DIR

KST = timezone(timedelta(hours=9))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
AUTHORIZED_CHAT_ID = int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None

# 한국어 티커 별칭
TICKER_ALIASES: dict[str, str] = {
    "삼성전자": "005930.KS",
    "하이닉스": "000660.KS",
    "sk하이닉스": "000660.KS",
    "네이버": "035420.KS",
    "카카오": "035720.KS",
    "셀트리온": "068270.KS",
    "애플": "AAPL",
    "마이크로소프트": "MSFT",
    "엔비디아": "NVDA",
    "구글": "GOOGL",
    "아마존": "AMZN",
    "메타": "META",
    "테슬라": "TSLA",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Telegram API ──────────────────────────────────────────────────────────────

def _post(method: str, **kwargs) -> dict:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}",
            timeout=15,
            **kwargs,
        )
        return resp.json() if resp.status_code == 200 else {}
    except Exception as e:
        log.error(f"{method} 실패: {e}")
        return {}


def reply(chat_id: int, text: str):
    send_message(text, str(chat_id))


def get_updates(offset: int | None) -> list:
    params: dict = {"timeout": 30, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params=params,
            timeout=40,
        )
        if resp.status_code == 200:
            return resp.json().get("result", [])
    except Exception as e:
        log.error(f"getUpdates 실패: {e}")
    return []


# ── Command Handlers ──────────────────────────────────────────────────────────

def handle_help(chat_id: int):
    msg = (
        "*stock-explorer 봇 명령어*\n\n"
        "`/explore TICKER` / `탐험 TICKER`\n"
        "  → 6에이전트 풀 탐험 (1~2분 소요)\n\n"
        "`/top` / `탑픽`\n"
        "  → 오늘 BUY+ 종목 요약\n\n"
        "`/scan TICKER` / `스캔 TICKER`\n"
        "  → 빠른 가격·RSI·MACD 스냅샷\n\n"
        "`/help` / `도움말`\n"
        "  → 이 목록\n\n"
        "_한국어 종목명도 지원: 삼성전자, 하이닉스, 네이버 등_"
    )
    reply(chat_id, msg)


def handle_explore(chat_id: int, ticker: str):
    ticker = TICKER_ALIASES.get(ticker.lower(), ticker.upper())
    reply(chat_id, f"[{ticker}] 데이터 수집 + 6에이전트 토론 중... (1~2분)")
    try:
        context = build_context(ticker)
    except Exception as e:
        reply(chat_id, f"[{ticker}] 데이터 수집 실패: {e}")
        return

    try:
        result = ExplorationModerator().run(context)
    except Exception as e:
        reply(chat_id, f"[{ticker}] 토론 실패: {e}")
        return

    send_exploration_result(result, str(chat_id))

    # 저널 저장
    try:
        from src.output.formatter import save_journal
        save_journal(result, JOURNALS_DIR)
    except Exception:
        pass


def handle_top(chat_id: int):
    """오늘 날짜 저널에서 BUY+ 종목을 읽어 요약한다."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    journals = list(JOURNALS_DIR.glob(f"{today}_explore_*.md"))

    if not journals:
        reply(chat_id, f"오늘({today}) 저장된 탐험 결과가 없습니다.\nGitHub Actions 결과를 기다리거나 `/explore TICKER`로 직접 실행해보세요.")
        return

    lines = [f"*오늘의 탑픽 ({today})*", ""]
    buy_signals = {Signal.STRONG_BUY, Signal.BUY}
    found = []

    for path in sorted(journals):
        content = path.read_text(encoding="utf-8")
        # 저널 헤더에서 신호 파싱
        for line in content.splitlines():
            if "강력매수" in line or "매수검토" in line:
                ticker = path.stem.split("_explore_")[-1]
                signal = "⬆⬆ 강력매수" if "강력매수" in line else "⬆ 매수검토"
                # 신뢰도 추출
                import re
                conf_match = re.search(r"신뢰도 \*\*(\d+)%\*\*", content)
                conf = conf_match.group(1) + "%" if conf_match else "?"
                found.append(f"{signal} *{ticker}* (신뢰도 {conf})")
                break

    if found:
        lines.extend(found)
    else:
        lines.append("오늘 BUY+ 종목 없음")

    lines += ["", "_※ 투자 결정의 책임은 본인에게 있습니다_"]
    reply(chat_id, "\n".join(lines))


def handle_scan(chat_id: int, ticker: str):
    """빠른 가격·RSI·MACD 스냅샷 (full exploration 없이)."""
    ticker = TICKER_ALIASES.get(ticker.lower(), ticker.upper())
    reply(chat_id, f"{ticker} 스캔 중...")

    try:
        data = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if data is None or len(data) < 2:
            reply(chat_id, f"{ticker} 데이터 조회 실패.")
            return
    except Exception as e:
        reply(chat_id, f"{ticker} 조회 오류: {e}")
        return

    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()

    price = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    change_pct = (price - prev) / prev * 100

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rsi_val = float(100 - 100 / (1 + gain / loss).iloc[-1]) if len(close) > 14 else None

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_cross = "골든크로스 📈" if macd_line.iloc[-1] > signal_line.iloc[-1] else "데드크로스 📉"

    # SMA
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    sma50_str = f"{sma50:,.2f}" if sma50 else "N/A"
    sma50_pos = ("현재가 위 ↑" if price > sma50 else "현재가 아래 ↓") if sma50 else ""

    # RSI 해석
    if rsi_val is None:
        rsi_str, rsi_comment = "N/A", ""
    elif rsi_val <= 30:
        rsi_str, rsi_comment = f"{rsi_val:.1f}", "과매도 — 반등 가능성"
    elif rsi_val >= 70:
        rsi_str, rsi_comment = f"{rsi_val:.1f}", "과매수 — 조정 가능성"
    else:
        rsi_str, rsi_comment = f"{rsi_val:.1f}", "중립"

    now_kst = datetime.now(KST).strftime("%m/%d %H:%M")
    msg = (
        f"*{ticker} 스캔* ({now_kst} KST)\n"
        f"현재가: *{price:,.2f}* ({change_pct:+.2f}%)\n\n"
        f"📊 RSI {rsi_str} — {rsi_comment}\n"
        f"📈 SMA50 {sma50_str} — {sma50_pos}\n"
        f"🔀 MACD {macd_cross}"
    )
    reply(chat_id, msg)


# ── Router ────────────────────────────────────────────────────────────────────

def handle_message(text: str, chat_id: int):
    if AUTHORIZED_CHAT_ID and chat_id != AUTHORIZED_CHAT_ID:
        log.warning(f"미인가 chat_id: {chat_id} — 무시")
        return

    lower = text.strip().lower()
    parts = text.strip().split(None, 1)

    if lower in ("도움말", "/help", "help"):
        handle_help(chat_id)

    elif lower in ("탑픽", "/top", "top"):
        handle_top(chat_id)

    elif lower.startswith(("/explore ", "탐험 ")):
        ticker = parts[1].strip() if len(parts) > 1 else ""
        if ticker:
            handle_explore(chat_id, ticker)
        else:
            reply(chat_id, "사용법: `/explore TICKER` (예: `/explore NVDA`)")

    elif lower.startswith(("/scan ", "스캔 ")):
        ticker = parts[1].strip() if len(parts) > 1 else ""
        if ticker:
            handle_scan(chat_id, ticker)
        else:
            reply(chat_id, "사용법: `/scan TICKER` (예: `/scan AAPL`)")

    else:
        handle_help(chat_id)


# ── Main Loop ─────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN 미설정")
        sys.exit(1)

    log.info("stock-explorer Telegram 봇 시작 (long polling)")
    offset: int | None = None

    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            text = msg.get("text", "")
            chat_id = msg.get("chat", {}).get("id")
            if text and chat_id:
                log.info(f"[{chat_id}] {text!r}")
                try:
                    handle_message(text, chat_id)
                except Exception as e:
                    log.error(f"핸들러 오류: {e}")
                    reply(chat_id, f"오류 발생: {e}")

        if not updates:
            time.sleep(1)


if __name__ == "__main__":
    main()
