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

## 파일 구조 (핵심)

```
src/agents/
  models.py          ← Signal(STRONG_BUY/BUY/WATCH/PASS/AVOID), StockAnalysisContext, ExplorationResult
  base_agent.py      ← StockAgent 추상 클래스 (evaluate, rebut, _latest_indicators)
  moderator.py       ← ExplorationModerator: 5단계 토론 프로세스
  fundamental_agent.py  ← 수익성·성장성·재무건전성 (Net Debt/EBITDA 로직 포함)
  valuation_agent.py    ← P/E·P/B·PEG·EV/EBITDA
  growth_agent.py       ← 매출 CAGR·EPS성장
  moat_agent.py         ← 해자·가격결정력
  momentum_agent.py     ← 기술적 지표
  risk_agent.py         ← 리스크 평가·거부권 (Net Debt/EBITDA·FCF 보정 포함)

src/pipeline/context_builder.py  ← yfinance → StockAnalysisContext 조립
src/output/formatter.py          ← Markdown + 터미널 출력
src/utils/config.py              ← 탐험 유니버스, 임계값
scripts/explore.py               ← 메인 진입점
```

## 토론 흐름 (moderator.py)

```
1. _collect_opinions()   — 6개 에이전트 독립 평가
2. _cross_examine()      — 상충 의견 쌍 교차 반박
3. _tally_votes()        — positive/neutral/negative 집계
4. _determine_signal()   — confidence 가중 투표로 최종 신호
5. _classify_urgency()   — UNANIMOUS / MAJORITY / SPLIT / RED_FLAG
```

## 주요 데이터 흐름

```python
context = build_context("AAPL")          # yfinance 수집
result = ExplorationModerator().run(context)  # 토론
print(format_terminal(result))           # 출력
save_journal(result)                     # data/journals/ 저장
```

## 알려진 엣지 케이스

| 케이스 | 문제 | 해결 |
|--------|------|------|
| 자사주매입 기업 (Apple 등) | D/E 100x+ 오경보 | Net Debt/EBITDA로 대체, Net Debt < 0 = 순현금 |
| current ratio < 1.0 | 유동성 위기 오경보 | FCF마진 > 15% 시 패널티 경감 |
| fundamentals={} | max_score 산정 오류 | has_debt_data 플래그로 조건부 처리 |
| pandas_ta 없음 (py3.11) | ImportError | ta 라이브러리로 대체 |

## GitHub Actions

| 워크플로우 | 파일 | 스케줄 | 내용 |
|-----------|------|--------|------|
| CI | `ci.yml` | push/PR | pytest 자동 실행 |
| Daily Highlights | `daily-highlights.yml` | 평일 10:00 KST | `--universe --min-signal BUY` |
| Weekend Full Scan | `weekly-scan.yml` | 토요일 10:00 KST | `--universe` (전체) |

Actions 봇이 결과를 `data/journals/`에 자동 커밋.
`workflow_dispatch`로 수동 실행 가능.

## 개발 환경

- Python 3.11, ta 0.11.0, yfinance 1.2.0, pandas 3.0.1
- pytest 9.0.2 / 테스트: `python3 -m pytest tests/ -v`
- SSH: `git@github.com` → Jaeman-Lee 기본 (`~/.ssh/id_ed25519_jaeman`)
- beautifulNH: `git@github-beautifulNH:...` 별칭 사용
- Notion DB: 프로젝트 (3169b0eb-a8a0-801c-9f7c-cafdf8f0e434)

## 세션 이력

| 날짜 | 주요 작업 |
|------|----------|
| 2026-03-02 | 초기 구조 + 6 에이전트 구현, D/E 보정, 테스트 11/11, 6종목 실행, GitHub 레포·Actions 설정, SSH 전환, Notion 등록 |
