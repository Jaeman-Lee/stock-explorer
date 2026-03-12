"""종목 탐험 실행 스크립트.

사용법:
    python scripts/explore.py AAPL               # 단일 종목
    python scripts/explore.py AAPL MSFT NVDA     # 복수 종목
    python scripts/explore.py --universe         # 기본 유니버스 전체
    python scripts/explore.py --dry-run AAPL     # 저널 저장 안 함
    python scripts/explore.py --min-signal BUY   # 특정 신호 이상만 출력
    python scripts/explore.py --notify --universe # 결과 Telegram 전송
    python scripts/explore.py --max-pe 25 --min-growth 0.15 --universe  # 스크리닝 필터
    python scripts/explore.py --sector Tech --top 5 --universe          # 업종 + 상위 N
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.models import ExplorationResult, Signal, StockAnalysisContext
from src.agents.moderator import ExplorationModerator
from src.output.formatter import format_terminal, save_journal
from src.pipeline.context_builder import build_context
from src.utils.config import (
    DEFAULT_UNIVERSE, EU_UNIVERSE, JOURNALS_DIR, LOG_LEVEL, LOG_FORMAT,
)
try:
    from src.utils.config import DAX40, EU_DEFENSE, EU_ENERGY, EU_TECH
except ImportError:
    DAX40 = EU_DEFENSE = EU_ENERGY = EU_TECH = []

# ── 로깅 초기화 ──────────────────────────────────────────────────────────────
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format=LOG_FORMAT)
logger = logging.getLogger(__name__)


@dataclass
class ScreeningFilters:
    """스크리닝 필터 옵션."""

    max_pe: float | None = None
    min_growth: float | None = None
    min_margin: float | None = None
    max_debt: float | None = None
    sector: str | None = None
    top: int | None = None


@dataclass
class AnalysisEntry:
    """분석 결과 + 컨텍스트를 함께 보관."""

    result: ExplorationResult
    context: StockAnalysisContext


def apply_screening_filters(
    entries: list[AnalysisEntry],
    filters: ScreeningFilters,
) -> list[AnalysisEntry]:
    """분석 완료 후 스크리닝 필터를 적용한다."""
    filtered = []
    for entry in entries:
        f = entry.context.fundamentals

        # --max-pe: trailing P/E 상한
        if filters.max_pe is not None:
            pe = f.get("trailingPE")
            if pe is None or pe > filters.max_pe:
                logger.info("[%s] 필터 제외: P/E %.1f > %.1f", entry.result.ticker, pe or 0, filters.max_pe)
                continue

        # --min-growth: 매출 성장률 하한
        if filters.min_growth is not None:
            growth = f.get("revenueGrowth")
            if growth is None or growth < filters.min_growth:
                logger.info("[%s] 필터 제외: 매출성장 %.1f%% < %.1f%%", entry.result.ticker, (growth or 0) * 100, filters.min_growth * 100)
                continue

        # --min-margin: 영업이익률 하한
        if filters.min_margin is not None:
            margin = f.get("operatingMargins")
            if margin is None or margin < filters.min_margin:
                logger.info("[%s] 필터 제외: 영업이익률 %.1f%% < %.1f%%", entry.result.ticker, (margin or 0) * 100, filters.min_margin * 100)
                continue

        # --max-debt: 부채비율 상한
        if filters.max_debt is not None:
            debt = f.get("debtToEquity")
            if debt is not None and debt > filters.max_debt:
                logger.info("[%s] 필터 제외: D/E %.1f > %.1f", entry.result.ticker, debt, filters.max_debt)
                continue

        # --sector: 업종 부분 매칭 (대소문자 무시)
        if filters.sector is not None:
            sector = f.get("sector") or ""
            if filters.sector.lower() not in sector.lower():
                logger.info("[%s] 필터 제외: 업종 '%s' != '%s'", entry.result.ticker, sector, filters.sector)
                continue

        filtered.append(entry)

    # --top: confidence 기준 상위 N개
    if filters.top is not None:
        filtered.sort(key=lambda e: e.result.final_confidence, reverse=True)
        filtered = filtered[: filters.top]

    return filtered


def format_summary_table(entries: list[AnalysisEntry]) -> str:
    """복수 종목 스크리닝 결과 요약 테이블을 생성한다."""
    if not entries:
        return ""

    # confidence 내림차순 정렬
    sorted_entries = sorted(entries, key=lambda e: e.result.final_confidence, reverse=True)

    lines = [
        "",
        "\u2550" * 70,
        "  스크리닝 결과 요약",
        "\u2550" * 70,
        f"  {'#':<4}{'종목':<10}{'신호':<14}{'확신도':<9}{'P/E':<9}{'매출성장':<11}{'업종'}",
        "  " + "-" * 66,
    ]

    for idx, entry in enumerate(sorted_entries, 1):
        r = entry.result
        f = entry.context.fundamentals

        pe = f.get("trailingPE")
        pe_str = f"{pe:.1f}" if pe is not None else "N/A"

        growth = f.get("revenueGrowth")
        growth_str = f"{growth:+.0%}" if growth is not None else "N/A"

        sector = f.get("sector") or "N/A"

        lines.append(
            f"  {idx:<4}{r.ticker:<10}{r.final_signal.value:<14}"
            f"{r.final_confidence:.2f}     {pe_str:<9}{growth_str:<11}{sector}"
        )

    lines.append("\u2550" * 70)
    return "\n".join(lines)


def explore_ticker(
    ticker: str,
    dry_run: bool = False,
    min_signal: Signal | None = None,
    notify: bool = False,
) -> AnalysisEntry | None:
    """단일 종목을 탐험하고 결과를 출력한다. 분석 엔트리를 반환한다."""
    print(f"\n[{ticker}] 데이터 수집 중...", end="", flush=True)
    try:
        context = build_context(ticker)
        print(" 완료")
    except Exception as e:
        print(f" 실패: {e}")
        logger.error("[%s] 데이터 수집 실패: %s", ticker, e)
        return None

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
            return None

    # 터미널 출력
    print(format_terminal(result))

    # 저널 저장 + DB 저장
    if not dry_run:
        journal_path = save_journal(result, JOURNALS_DIR)
        print(f"  리포트 저장: {journal_path}")

        from src.storage.database import ExplorationDB
        db = ExplorationDB()
        db.save_result(result, report_path=str(journal_path))
        print(f"  DB 저장 완료")

    # Telegram 전송
    if notify:
        from src.telegram.sender import send_exploration_result
        send_exploration_result(result)
        print(f"  Telegram 전송 완료")

    return AnalysisEntry(result=result, context=context)


def main() -> None:
    parser = argparse.ArgumentParser(description="투자 종목 탐험기")
    parser.add_argument("tickers", nargs="*", help="분석할 종목 심볼")
    parser.add_argument(
        "--universe", action="store_true", help="기본 유니버스 전체 탐험 (미국)"
    )
    parser.add_argument(
        "--eu", action="store_true", help="유럽 유니버스 탐험 (DAX 40 + EU 섹터)"
    )
    parser.add_argument(
        "--eu-all", action="store_true", help="미국 + 유럽 전체 탐험"
    )
    parser.add_argument(
        "--prescreen", action="store_true",
        help="사전 스크리닝: 전체 유니버스 점수화 후 상위 30종목만 풀 분석"
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

    # ── 스크리닝 필터 ─────────────────────────────────────────────────────────
    parser.add_argument(
        "--max-pe", type=float, default=None,
        help="trailing P/E 상한 (예: 25.0)",
    )
    parser.add_argument(
        "--min-growth", type=float, default=None,
        help="최소 매출 성장률 (예: 0.15 = 15%%)",
    )
    parser.add_argument(
        "--min-margin", type=float, default=None,
        help="최소 영업이익률 (예: 0.10 = 10%%)",
    )
    parser.add_argument(
        "--max-debt", type=float, default=None,
        help="최대 부채비율 D/E (예: 2.0)",
    )
    parser.add_argument(
        "--sector", type=str, default=None,
        help="업종 필터 (부분 매칭, 예: Technology)",
    )
    parser.add_argument(
        "--top", type=int, default=None,
        help="상위 N개 종목만 표시 (confidence 기준)",
    )

    args = parser.parse_args()

    tickers = args.tickers
    if args.universe:
        tickers = DEFAULT_UNIVERSE
    elif args.eu:
        tickers = DAX40 + EU_DEFENSE + EU_ENERGY + EU_TECH
    elif args.eu_all:
        tickers = EU_UNIVERSE

    if args.prescreen and tickers:
        from src.pipeline.universe_builder import build_full_universe
        from src.pipeline.prescreener import prescreen
        universe = build_full_universe() if args.eu_all else list(tickers)
        tickers = prescreen(universe, top_n=30, defense_min=5)

    if not tickers:
        parser.print_help()
        sys.exit(1)

    min_signal = Signal(args.min_signal.lower()) if args.min_signal else None

    filters = ScreeningFilters(
        max_pe=args.max_pe,
        min_growth=args.min_growth,
        min_margin=args.min_margin,
        max_debt=args.max_debt,
        sector=args.sector,
        top=args.top,
    )
    has_filters = any(
        v is not None
        for v in [filters.max_pe, filters.min_growth, filters.min_margin,
                   filters.max_debt, filters.sector, filters.top]
    )

    print(f"\n투자 종목 탐험 시작 — {len(tickers)}개 종목")
    if has_filters:
        active = []
        if filters.max_pe is not None:
            active.append(f"P/E<={filters.max_pe}")
        if filters.min_growth is not None:
            active.append(f"매출성장>={filters.min_growth:.0%}")
        if filters.min_margin is not None:
            active.append(f"영업이익률>={filters.min_margin:.0%}")
        if filters.max_debt is not None:
            active.append(f"D/E<={filters.max_debt}")
        if filters.sector is not None:
            active.append(f"업종={filters.sector}")
        if filters.top is not None:
            active.append(f"상위 {filters.top}개")
        print(f"스크리닝 필터: {', '.join(active)}")
    print("=" * 60)

    entries: list[AnalysisEntry] = []
    for ticker in tickers:
        entry = explore_ticker(
            ticker.upper(), dry_run=args.dry_run,
            min_signal=min_signal, notify=args.notify,
        )
        if entry is not None:
            entries.append(entry)

    # 스크리닝 필터 적용
    if has_filters and entries:
        before_count = len(entries)
        entries = apply_screening_filters(entries, filters)
        print(f"\n스크리닝 필터 적용: {before_count}개 → {len(entries)}개 통과")

    # 복수 종목일 때 요약 테이블 출력
    if len(entries) > 1:
        print(format_summary_table(entries))

    print("\n탐험 완료.")


if __name__ == "__main__":
    main()
