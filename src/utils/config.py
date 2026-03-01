"""stock-explorer 중앙 설정.

fin-advisor config.py 패턴을 계승.
"""

from pathlib import Path

# ── 경로 ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
JOURNALS_DIR = DATA_DIR / "journals"

# ── 탐험 대상 유니버스 ─────────────────────────────────────────────────────────
# 미국 대형주 (S&P 500 대표 섹터별)
US_LARGE_CAP = [
    # 테크
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSM",
    # 금융
    "JPM", "BRK-B", "V", "MA",
    # 헬스케어
    "UNH", "JNJ", "LLY",
    # 소비재
    "COST", "HD", "NKE",
    # 에너지
    "XOM", "CVX",
    # 통신
    "T", "VZ",
]

# 고성장 중소형주 (성장주 탐험 대상)
GROWTH_CANDIDATES = [
    "PLTR", "SNOW", "CRWD", "DDOG", "MELI",
    "SE", "SHOP", "NET", "ZS", "OKTA",
]

# 한국 주식 (KRX)
KR_STOCKS = [
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
    "035420.KS",  # NAVER
    "035720.KS",  # 카카오
    "207940.KS",  # 삼성바이오로직스
    "068270.KS",  # 셀트리온
    "003550.KS",  # LG
    "051910.KS",  # LG화학
]

# 기본 탐험 유니버스 (전체 대상)
DEFAULT_UNIVERSE = US_LARGE_CAP + GROWTH_CANDIDATES

# ── 기술적 지표 기본값 (fin-advisor와 동일) ─────────────────────────────────
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0
SMA_PERIODS = [20, 50, 200]

# ── 탐험 필터 기준 ─────────────────────────────────────────────────────────
MIN_MARKET_CAP = 1_000_000_000        # 최소 시가총액 $10억
MIN_CONFIDENCE = 0.55                 # 최소 신뢰도 55%
STRONG_BUY_CONFIDENCE = 0.75          # 강력 매수 신뢰도 임계값

# ── 리스크 임계값 (fin-advisor와 유사) ─────────────────────────────────────
MAX_DEBT_TO_EQUITY = 3.0
MIN_CURRENT_RATIO = 0.8
RISK_VETO_CONFIDENCE = 0.80           # 이 이상이면 리스크 에이전트 거부권 발동

# ── 데이터 수집 ─────────────────────────────────────────────────────────────
DEFAULT_LOOKBACK_DAYS = 90
MARKET_DATA_INTERVAL = "1d"

# ── 출력 설정 ────────────────────────────────────────────────────────────────
DEFAULT_OUTPUT_DIR = JOURNALS_DIR
CONSOLE_OUTPUT = True
