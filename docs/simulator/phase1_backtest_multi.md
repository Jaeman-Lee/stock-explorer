# Phase 1: 다기간 백테스트

## 목적

3/6/9/12개월 전 시점에서 에이전트 평가를 실행하고, 그 시점부터 현재까지 실제 수익률과 대조.
9개 전략별 신호를 동시 비교하여 시간축 편향 없는 성과 테이블을 생성한다.

## 데이터 흐름

```
입력: 30종목 × [3, 6, 9, 12]개월 전
  ↓
각 시점별 build_context() + 6개 에이전트 evaluate() — 1회만 실행
  ↓
에이전트 opinions JSON 캐시 저장 (재사용 가능)
  ↓
9개 전략별 apply_strategy() → 9개 신호 생성
  ↓
시점별 실제 가격 → 현재 가격 → 수익률 계산
  ↓
전략별 승률/수익률/스프레드 비교 테이블 출력
```

## 대상 종목 (30개)

US_LARGE_CAP(21) + KR 대표(3: 005930.KS, 000660.KS, 035420.KS) + 추가 대형주(6: AMD, AVGO, LLY, MA, ADBE, GE)

## 산출물

```
         | 3개월 spread | 6개월 spread | 9개월 | 12개월 | 평균 승률 |
---------|-------------|-------------|-------|--------|----------|
legacy   |             |             |       |        |          |
v1       |             |             |       |        |          |
v3       |             |             |       |        |          |
v3-bear  |             |             |       |        |          |
auto     |             |             |       |        |          |
```

## 사용법

```bash
python scripts/backtest_multi.py                    # 기본 30종목 × 4시점
python scripts/backtest_multi.py --months 3 6       # 특정 시점만
python scripts/backtest_multi.py --tickers AAPL MSFT # 특정 종목만
python scripts/backtest_multi.py --cache-only        # 캐시된 데이터로만 (API 호출 없음)
```

## 캐시 구조

`data/backtest_cache/` 디렉토리에 JSON 저장:
```
data/backtest_cache/
  AAPL_2026-01-06.json    # ticker_signaldate.json
  AAPL_2025-10-06.json
  ...
```

각 JSON:
```json
{
  "ticker": "AAPL",
  "signal_date": "2026-01-06",
  "regime": "neutral",
  "opinions": [
    {"agent": "fundamental-analyst", "signal": "buy", "confidence": 0.72, ...},
    ...
  ],
  "price_at_signal": 230.50,
  "price_current": 255.92,
  "return_pct": 11.03
}
```
