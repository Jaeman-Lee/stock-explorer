# Simulator — 전략 레지스트리 검증 서브프로젝트

## 목적

9개 신호 결정 전략(legacy, v1~v6, v3-bear, v3-defensive)의 실효성을 체계적으로 검증.
단일 구간 편향을 제거하고, 다양한 시장 환경에서 전략별 성과를 비교한다.

## 5단계 검증 파이프라인

```
Phase 1 (다기간 백테스트)     ← 30종목 × 4시점 = 120회 에이전트 실행
    ↓
Phase 2 (레짐별 분석)        ← Phase 1 결과를 bull/neutral/bear로 분류
    ↓
Phase 4 (감도 분석)          ← Phase 1 캐시 재사용, 파라미터 그리드 서치
    ↓
Phase 3 (롤링 시뮬)          ← 52주 누적 수익 곡선 + 샤프/낙폭
    ↓
Phase 5 (실전 A/B)           ← 4주 라이브 legacy vs auto 비교
```

## 스크립트

| 스크립트 | Phase | 설명 |
|----------|-------|------|
| `scripts/backtest_multi.py` | 1 | 다기간(3/6/9/12개월) × 9전략 백테스트 |
| `scripts/regime_analysis.py` | 2 | 레짐별 × 전략별 성과 매트릭스 |
| `scripts/rolling_sim.py` | 3 | 52주 롤링 누적 수익 시뮬레이션 |
| `scripts/sensitivity.py` | 4 | 파라미터 그리드 서치 감도 분석 |
| `scripts/track_returns.py` | 5 | 라이브 탐험 후 수익률 자동 추적 |

## 기존 도구 (참고)

| 스크립트 | 설명 |
|----------|------|
| `scripts/backtest.py` | 단일 시점 백테스트 (Phase 1의 전신) |
| `scripts/simulate_scenarios.py` | 저널 기반 전략 시뮬레이션 (오늘 작성) |
| `scripts/simulate_new_rules.py` | 단일 규칙 변경 시뮬레이션 |

## 검증 기준

| Phase | 성공 기준 |
|-------|----------|
| 1 | 4개 시점 × 30종목 데이터 확보, 전략별 스프레드 테이블 생성 |
| 2 | bull/neutral/bear 각 구간에서 auto가 고정 전략 대비 우위 |
| 3 | 52주 롤링에서 auto 누적 수익 > legacy + 낙폭 < legacy |
| 4 | 최적 파라미터가 V3 대비 스프레드 +1%p 이상 개선 |
| 5 | 4주 라이브 A/B에서 auto 승률 > legacy 승률 |

## 핵심 제약

- yfinance `info`는 항상 현재 기준 → 과거 fundamentals 완전 재현 불가
- market_data(OHLCV+기술지표)는 과거 재현 가능
- Phase 1이 가장 비용 큼 (120회 yfinance API 호출)
- Phase 4는 Phase 1 캐시 재사용으로 추가 API 호출 없음
