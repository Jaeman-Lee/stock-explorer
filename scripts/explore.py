"""종목 탐험 실행 스크립트.

사용법:
    python scripts/explore.py AAPL               # 단일 종목
    python scripts/explore.py AAPL MSFT NVDA     # 복수 종목
    python scripts/explore.py --universe         # 기본 유니버스 전체
    python scripts/explore.py --dry-run AAPL     # 저널 저장 안 함
    python scripts/explore.py --min-signal BUY   # 특정 신호 이상만 출력
    python scripts/explore.py --notify --universe # 결과 Telegram 전송
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.models import Signal
from src.agents.moderator import ExplorationModerator
from src.output.formatter import format_terminal, save_journal
from src.pipeline.context_builder import build_context
from src.utils.config import DEFAULT_UNIVERSE, JOURNALS_DIR


def explore_ticker(
    ticker: str,
    dry_run: bool = False,
    min_signal: Signal | None = None,
    notify: bool = False,
) -> None:
    """단일 종목을 탐험하고 결과를 출력한다."""
    print(f"\n[{ticker}] 데이터 수집 중...", end="", flush=True)
    try:
        context = build_context(ticker)
        print(" 완료")
    except Exception as e:
        print(f" 실패: {e}")
        return

    print(f"[{ticker}] 토론 진행 중...", end="", flush=True)
    moderator = ExplorationModerator()
    result = moderator.run(context)
    print(" 완료")

    # 신호 필터
    SIGNAL_ORDER = [Signal.STRONG_BUY, Signal.BUY, Signal.WATCH, Signal.PASS, Signal.AVOID]
    if min_signal:
        min_idx = SIGNAL_ORDER.index(min_signal)
        result_idx = SIGNAL_ORDER.index(result.final_signal)
        if result_idx > min_idx:
            print(f"[{ticker}] 신호 {result.final_signal.value} — 필터 기준 미달, 생략")
            return

    # 터미널 출력
    print(format_terminal(result))

    # 저널 저장
    if not dry_run:
        journal_path = save_journal(result, JOURNALS_DIR)
        print(f"  리포트 저장: {journal_path}")

    # Telegram 전송
    if notify:
        from src.telegram.sender import send_exploration_result
        send_exploration_result(result)
        print(f"  Telegram 전송 완료")


def main() -> None:
    parser = argparse.ArgumentParser(description="투자 종목 탐험기")
    parser.add_argument("tickers", nargs="*", help="분석할 종목 심볼")
    parser.add_argument(
        "--universe", action="store_true", help="기본 유니버스 전체 탐험"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="저널 파일 저장 안 함"
    )
    parser.add_argument(
        "--min-signal",
        choices=["STRONG_BUY", "BUY", "WATCH", "PASS", "AVOID"],
        default=None,
        help="이 신호 이상인 종목만 출력",
    )
    parser.add_argument(
        "--notify", action="store_true", help="결과를 Telegram으로 전송"
    )
    args = parser.parse_args()

    tickers = args.tickers
    if args.universe:
        tickers = DEFAULT_UNIVERSE

    if not tickers:
        parser.print_help()
        sys.exit(1)

    min_signal = Signal(args.min_signal.lower()) if args.min_signal else None

    print(f"\n투자 종목 탐험 시작 — {len(tickers)}개 종목")
    print("=" * 60)

    results_summary = []
    for ticker in tickers:
        explore_ticker(ticker.upper(), dry_run=args.dry_run, min_signal=min_signal, notify=args.notify)

    print("\n탐험 완료.")


if __name__ == "__main__":
    main()
