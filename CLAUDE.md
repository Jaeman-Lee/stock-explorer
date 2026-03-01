# stock-explorer — 투자 종목 탐험기

**fin-advisor** 프로젝트의 멀티 에이전트 토론 아키텍처를 계승하여
신규 투자 종목을 발굴·탐험하는 시스템.

## 목적

포트폴리오 관리(fin-advisor) → **신규 종목 발굴 특화**
"어떤 종목을 처음 사야 할까?" 에 답하는 도구.

## 아키텍처 (fin-advisor 계승)

```
yfinance 데이터 수집
        ↓
StockAnalysisContext 조립 (context_builder.py)
        ↓
5개 전문 에이전트 독립 평가
  ├─ fundamental-analyst : 수익성·성장성·재무건전성
  ├─ valuation-analyst   : P/E·P/B·PEG·EV/EBITDA
  ├─ growth-analyst      : 매출 성장·EPS·CAGR
  ├─ moat-analyst        : 경쟁 해자·가격결정력·시장 지위
  └─ risk-analyst        : 부채·유동성·현금소진 (거부권)
        ↓
ExplorationModerator (토론 사회자)
  ├─ Phase 1: 독립 평가
  ├─ Phase 2: 교차 반박
  ├─ Phase 3: confidence 가중 투표
  └─ Phase 4: 긴급도 분류 (unanimous/majority/split/red_flag)
        ↓
ExplorationResult → Markdown 리포트 저장
```

## fin-advisor에서 계승한 패턴

| 패턴 | fin-advisor 출처 | 변경 사항 |
|------|-----------------|----------|
| BaseAgent + evaluate/rebut | `debate/base_agent.py` | StrategyAgent → StockAgent |
| 데이터 모델 (Signal, Urgency, Opinion, Result) | `debate/models.py` | HOLD→WATCH, SELL→PASS/AVOID 재정의 |
| 토론 사회자 (투표, 교차반박) | `debate/moderator.py` | 포트폴리오 컨텍스트 제거 |
| 컨텍스트 빌더 | `debate/context_builder.py` | 재무이력·피어비교 필드 추가 |
| 기술적 지표 에이전트 | `debate/agents/momentum_trader.py` | 그대로 이식 |
| Markdown 리포트 + 저널 저장 | `debate/router.py` | Telegram 제거, 로컬 저장만 |
| config.py 구조 | `utils/config.py` | 탐험 유니버스·필터 임계값 추가 |

## 빠른 시작

```bash
# 의존성 설치
pip install -r requirements.txt

# 단일 종목 탐험
python scripts/explore.py AAPL

# 복수 종목
python scripts/explore.py AAPL MSFT NVDA

# 기본 유니버스 전체 탐험
python scripts/explore.py --universe

# 매수 신호 이상인 종목만 출력
python scripts/explore.py --universe --min-signal BUY

# 저널 저장 없이 터미널만 출력
python scripts/explore.py --dry-run GOOGL
```

## 프로젝트 구조

```
src/
  agents/
    models.py          # Signal, Urgency, StockAnalysisContext, ExplorationResult
    base_agent.py      # StockAgent 추상 기반 클래스
    moderator.py       # ExplorationModerator (토론 사회자)
    fundamental_agent.py  # 재무 기반 평가
    valuation_agent.py    # 밸류에이션 평가
    growth_agent.py       # 성장성 평가
    moat_agent.py         # 경쟁 해자 평가
    momentum_agent.py     # 기술적 분석 (fin-advisor 이식)
    risk_agent.py         # 리스크 평가 (거부권)
  pipeline/
    context_builder.py    # yfinance → StockAnalysisContext
  output/
    formatter.py          # Markdown 리포트 + 터미널 출력
  utils/
    config.py             # 탐험 유니버스, 임계값, 경로
scripts/
  explore.py             # 메인 실행 스크립트
data/
  journals/              # Markdown 분석 리포트 저장소
tests/                   # pytest 테스트
```

## 에이전트 신호 체계

| 신호 | 의미 | 행동 |
|------|------|------|
| `strong_buy` | 강력 매수 추천 | 즉시 상세 분석 → 포트폴리오 편입 검토 |
| `buy` | 매수 검토 | 추가 분석 후 진입 |
| `watch` | 관심종목 | 진입 조건 설정 후 모니터링 |
| `pass` | 패스 | 현재 기준 투자 부적합 |
| `avoid` | 회피 | 명확한 결격 사유 있음 |

## 확장 계획

- [ ] `sector_peers` 자동 수집 (동종 업체 밸류에이션 비교)
- [ ] `sentiment_data` 뉴스 감성 분석 통합 (fin-advisor news_collector 재사용)
- [ ] `macro_snapshot` FRED 연동 (fin-advisor fred_data 재사용)
- [ ] SQLite DB 저장 (fin-advisor database 패턴 적용)
- [ ] 스크리닝 필터 (PER < 20 AND 매출성장 > 15% 등)
- [ ] Telegram 알림 (fin-advisor telegram_sender 재사용)
- [ ] 주간 유니버스 스캔 + 요약 리포트

## 핵심 규칙

- 각 에이전트는 **독립적으로** 평가 (다른 에이전트 결과 참조 금지)
- 리스크 에이전트 AVOID + confidence ≥ 0.8 → 자동 RED_FLAG (거부권)
- 모든 분석 결과에 **면책조항** 포함
- 기술적 지표는 `pandas_ta` 사용 (fin-advisor와 동일)
