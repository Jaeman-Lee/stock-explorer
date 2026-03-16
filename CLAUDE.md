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
6개 전문 에이전트 독립 평가 (±5% 지터로 토론 다양성 확보)
  ├─ fundamental-analyst : 수익성·성장성·재무건전성·주주환원 (섹터별 임계값)
  ├─ valuation-analyst   : P/E·P/B·PEG·EV/EBITDA (피어 자동 비교)
  ├─ growth-analyst      : 매출 성장·EPS·CAGR (배당주 하한선)
  ├─ moat-analyst        : 경쟁 해자·가격결정력·시장 지위
  ├─ momentum-analyst    : RSI·MACD·SMA·볼린저밴드
  └─ risk-analyst        : 부채·유동성·현금소진 (소프트/하드 거부권)
        ↓
ExplorationModerator (토론 사회자)
  ├─ Phase 1: 독립 평가
  ├─ Phase 2: 교차 반박
  ├─ Phase 3: 합의 폭 보상 가중 투표
  ├─ Phase 4: 밸류에이션 드래그 + 매크로 레짐 반영
  └─ Phase 5: 긴급도 분류 (unanimous/majority/split/red_flag)
        ↓
ExplorationResult → Markdown 리포트 + SQLite 저장
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

# 스크리닝 필터 사용
python scripts/explore.py --universe --max-pe 25 --min-growth 0.15 --sector Technology --top 5
```

## 프로젝트 구조

```
src/
  agents/
    models.py          # Signal, Urgency, DataQuality, StockAnalysisContext, ExplorationResult
    base_agent.py      # StockAgent 추상 기반 클래스 (_jitter, _get_thresholds, _safe_ratio)
    moderator.py       # ExplorationModerator (합의 폭 보상 투표, 소프트/하드 거부권, 밸류에이션 드래그, 매크로 레짐)
    fundamental_agent.py  # 재무 기반 평가 (섹터별 마진 임계값, 주주환원)
    valuation_agent.py    # 밸류에이션 평가 (섹터별 P/E 밴드, 피어 비교)
    growth_agent.py       # 성장성 평가 (CAGR, 추이, 배당주 하한선)
    moat_agent.py         # 경쟁 해자 평가 (섹터별 피어 GM)
    momentum_agent.py     # 기술적 분석 (RSI, MACD, SMA, BB)
    risk_agent.py         # 리스크 평가 (Net Debt/EBITDA, 소프트/하드 거부권)
  pipeline/
    context_builder.py    # yfinance → StockAnalysisContext (피어 자동 수집, .KS 대응, 매크로 레짐)
    data_validator.py     # 펀더멘탈 검증, NaN/Inf 필터, DataQuality 평가
  storage/
    database.py           # SQLite 저장 (explorations + agent_opinions, 신호 변화 추적)
  output/
    formatter.py          # Markdown 리포트 + 터미널 출력
  telegram/
    sender.py             # Telegram 알림 전송
  utils/
    config.py             # 유니버스, 섹터별 임계값/피어, 지터, 밸류에이션 드래그, 로깅
scripts/
  explore.py             # 메인 CLI (스크리닝 필터, 요약 테이블, DB 저장)
  backtest.py            # 백테스트 (과거 신호 vs 실제 수익률)
  telegram_bot.py        # 양방향 Telegram 봇
data/
  journals/              # Markdown 분석 리포트 저장소
  explorations.db        # SQLite 분석 이력 DB
tests/                   # pytest 테스트 (38개)
```

## 에이전트 신호 체계

| 신호 | 의미 | 행동 |
|------|------|------|
| `strong_buy` | 강력 매수 추천 | 즉시 상세 분석 → 포트폴리오 편입 검토 |
| `buy` | 매수 검토 | 추가 분석 후 진입 |
| `watch` | 관심종목 | 진입 조건 설정 후 모니터링 |
| `pass` | 패스 | 현재 기준 투자 부적합 |
| `avoid` | 회피 | 명확한 결격 사유 있음 |

## 구현 완료

- [x] `sector_peers` 자동 수집 (8개 섹터 × 3-5 피어, 1시간 캐시)
- [x] SQLite DB 저장 (`explorations` + `agent_opinions`, 신호 변화 추적)
- [x] 스크리닝 필터 (`--max-pe`, `--min-growth`, `--min-margin`, `--max-debt`, `--sector`, `--top`)
- [x] 지터 시스템 (±5% 임계값 노이즈 → 토론 다양성)
- [x] 섹터별 임계값 (8개 섹터별 P/E·마진 밴드)
- [x] 소프트/하드 거부권 (0.70 소프트, 0.85 하드)
- [x] 합의 폭 보상 투표 (breadth bonus)
- [x] 한국주식(.KS) MultiIndex 데이터 수정
- [x] NaN/Inf 필터링, div-by-zero 방어, 구조화 로깅
- [x] Telegram 알림 (sender + 양방향 봇)
- [x] 가치주 점수 보정: 주주환원 10점 섹션 (배당수익률 기반), 성장 30→20점 축소
- [x] 배당주 하한선: growth-analyst에서 배당 2%+ & 비역성장 → 최소 WATCH 보장
- [x] 매크로 오버레이: S&P500/VIX 기반 시장 레짐(bear/neutral/bull) 판정 → confidence 조정
- [x] 밸류에이션 드래그: 최종 BUY인데 valuation PASS/AVOID(conf≥0.60) → confidence -10%
- [x] 백테스트 스크립트 (`scripts/backtest.py`)

## 확장 계획

- [ ] `sentiment_data` 뉴스 감성 분석 통합 (fin-advisor news_collector 재사용)
- [ ] `macro_snapshot` FRED 연동 확장 (현재 S&P500/VIX 레짐만, FRED 금리·고용 추가)
- [ ] 주간 유니버스 스캔 + 요약 리포트
- [ ] 신호 변화 대시보드 (SQLite 기반)

## 핵심 규칙

- 각 에이전트는 **독립적으로** 평가 (다른 에이전트 결과 참조 금지)
- 리스크 에이전트 **하드 거부**: AVOID + confidence ≥ 0.85 → RED_FLAG
- 리스크 에이전트 **소프트 거부**: AVOID + confidence ≥ 0.70 → confidence -15%
- **밸류에이션 드래그**: 최종 BUY/STRONG_BUY + valuation PASS/AVOID(conf≥0.60) → confidence -10%
- **매크로 레짐**: bear(VIX>25 & S&P<SMA50) → positive confidence -10%, bull(VIX<18 & S&P>SMA50) → +5%
- **배당주 하한선**: dividendYield≥2% & rev_growth≥0 → growth-analyst pct 최소 40% (WATCH 보장)
- 섹터별 임계값 적용 (Tech P/E 20-35-60 vs Energy 8-15-25 등)
- 지터(±5%) 활성화 시 매 토론마다 미세하게 다른 결과 (결정론적 문제 해결)
- 모든 분석 결과에 **면책조항** 포함
- 기술적 지표는 `ta` 라이브러리 사용
