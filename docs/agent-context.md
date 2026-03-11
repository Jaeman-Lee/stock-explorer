# stock-explorer — Agent Context

이 파일은 Claude Code 에이전트가 프로젝트 컨텍스트를 빠르게 파악하기 위한 문서다.
작업 전 반드시 읽을 것.

## 프로젝트 목적

"투자 종목 탐험기" — 포트폴리오 편입 후보 종목을 멀티 에이전트 토론으로 발굴.
`fin-advisor`(포트폴리오 관리)의 아키텍처를 계승해 신규 종목 발굴에 특화.

## 핵심 설계 원칙

1. **에이전트 독립성**: 각 에이전트는 다른 에이전트 결과를 보지 않고 독립 평가
2. **거부권**: `risk-analyst`가 AVOID + confidence ≥ 0.8 → RED_FLAG (전체 합의 무효화)
3. **D/E 왜곡 주의**: D/E 단독 사용 금지. Net Debt/EBITDA 우선. Net Debt < 0 = 순현금 = 강점
4. **FCF 보정**: current ratio < 1.0이라도 FCF마진 > 15%면 유동성 리스크 경감
5. **사전 스크리닝**: 500+종목 → prescreener 점수화 → 상위 30종목만 풀 분석

## 파일 구조 (핵심)

```
src/agents/
  models.py             ← Signal(STRONG_BUY/BUY/WATCH/PASS/AVOID), StockAnalysisContext, ExplorationResult
  base_agent.py         ← StockAgent 추상 클래스
  moderator.py          ← ExplorationModerator: 5단계 토론
  fundamental_agent.py  ← 수익성·재무건전성 (Net Debt/EBITDA 로직)
  valuation_agent.py    ← P/E·P/B·PEG·EV/EBITDA
  growth_agent.py       ← 매출 CAGR·EPS성장
  moat_agent.py         ← 해자·가격결정력
  momentum_agent.py     ← 기술적 지표 (ta 라이브러리)
  risk_agent.py         ← 리스크 평가·거부권

src/pipeline/
  context_builder.py    ← yfinance → StockAnalysisContext
  universe_builder.py   ← S&P 500 Wikipedia 수집 + build_full_universe()
  prescreener.py        ← 빠른 점수화, 방산 쿼터, top_n 선별

src/telegram/
  sender.py             ← ExplorationResult → Telegram 전송

src/output/formatter.py ← Markdown + 터미널 출력
src/utils/config.py     ← 유니버스 (DAX40, EU_DEFENSE/ENERGY/TECH), 임계값
scripts/explore.py      ← 메인 진입점
scripts/telegram_bot.py ← 양방향 Telegram 봇 (long polling)
```

## 데이터 흐름

```python
# 전체 파이프라인
universe = build_full_universe()              # S&P500 + DAX40 + EU섹터 ~580종목
candidates = prescreen(universe, top_n=30)   # 빠른 점수화 → 30종목
for ticker in candidates:
    context = build_context(ticker)           # yfinance 수집
    result = ExplorationModerator().run(context)  # 6에이전트 토론
    save_journal(result)                      # data/journals/ 저장
    send_exploration_result(result)           # Telegram 전송 (--notify 시)
```

## 유니버스 구성

| 유니버스 | 종목 수 | 내용 |
|---------|---------|------|
| `DEFAULT_UNIVERSE` | ~30 | 미국 대형주 + 성장주 |
| `DAX40` | 39 | DAX 전체 (RHM.DE 방산 포함) |
| `EU_DEFENSE` | 5 | BAE Systems, Thales, Safran, Hensoldt, Leonardo |
| `EU_ENERGY` | 6 | Shell, BP, TotalEnergies, Equinor, Eni, Ørsted |
| `EU_TECH` | 7 | ASML, STMicro, Dassault, Capgemini, Novartis, Roche, Nestlé |
| `EU_UNIVERSE` | ~580 | S&P500 + DAX40 + EU섹터 전체 (prescreener 입력) |

## 사전 스크리닝 기준 (prescreener.py)

| 항목 | 조건 | 점수 |
|------|------|------|
| 시총 | > $5B | +1 |
| RSI | 35~55 구간 | +2 |
| 추세 | 현재가 > SMA50 | +1 |
| 회복 후보 | 현재가 < SMA200 | +1 |
| 목표가 | 애널리스트 목표가 10%↑ | +2 |
| 성장 | 매출 YoY > 10% | +2 |
| 유동성 | 일평균 거래대금 $50M↑ | +1 |

방산 쿼터: `defense_min=5` (DEFENSE_TICKERS 명시 리스트 + industry="Aerospace & Defense")

## GitHub Actions

| 워크플로우 | 스케줄 | 내용 |
|-----------|--------|------|
| CI | push/PR | pytest 자동 실행 |
| Daily Highlights | 평일 10:00 KST | `--eu-all --prescreen --min-signal BUY --notify` |
| Weekend Full Scan | 토요일 10:00 KST | `--eu-all --prescreen --notify` |

예상 소요: 스크리닝 ~35분 + 풀 분석 ~60분 = **총 1.5시간**

## 알려진 엣지 케이스

| 케이스 | 문제 | 해결 |
|--------|------|------|
| 자사주매입 기업 (Apple 등) | D/E 100x+ 오경보 | Net Debt/EBITDA로 대체 |
| current ratio < 1.0 | 유동성 위기 오경보 | FCF마진 > 15% 시 패널티 경감 |
| fundamentals={} | max_score 오류 | has_debt_data 플래그 조건부 처리 |
| pandas_ta (py3.11) | ImportError | ta 라이브러리로 대체 |
| 유럽 종목 방산 분류 | yfinance industry 불명확 | DEFENSE_TICKERS 명시 리스트 병행 |
| DAX 40 구성 변경 | 분기별 리밸런싱 | config.py 주석에 확인 날짜 기재 |

## 개발 환경

- Python 3.11, ta 0.11.0, yfinance 1.2.0, pandas 3.0.1, requests 2.31.0
- 테스트: `python3 -m pytest tests/ -v`
- SSH: `git@github.com` → Jaeman-Lee 기본 (`~/.ssh/id_ed25519_jaeman`)
- Notion DB: 프로젝트 (3169b0eb-a8a0-801c-9f7c-cafdf8f0e434)
- Telegram 봇: `.env`에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 저장

## 세션 이력

| 날짜 | 주요 작업 |
|------|----------|
| 2026-03-02 | 초기 구조 + 6 에이전트 구현, D/E 보정, 테스트 11/11, GitHub·Actions·Notion 등록 |
| 2026-03-04 | GitHub Actions 등록, Telegram 양방향 봇, /explore·/scan·/top 명령어 |
| 2026-03-11 | 유럽 유니버스 추가, 사전 스크리닝 설계·구현, DAX 40 전체, EU 섹터 분리, Actions 최적화 |
