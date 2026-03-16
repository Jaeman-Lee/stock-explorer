"""stock-explorer 중앙 설정.

fin-advisor config.py 패턴을 계승.
"""

from pathlib import Path

# ── 경로 ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
JOURNALS_DIR = DATA_DIR / "journals"
DB_PATH = DATA_DIR / "explorations.db"

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

# ── DAX 40 전체 (XETRA, .DE) ──────────────────────────────────────────────────
# 분기별 구성 변경 가능 — 마지막 확인: 2026-03
DAX40 = [
    "ADS.DE",   # Adidas
    "AIR.DE",   # Airbus
    "ALV.DE",   # Allianz
    "BAS.DE",   # BASF
    "BAYN.DE",  # Bayer
    "BEI.DE",   # Beiersdorf
    "BMW.DE",   # BMW
    "BNR.DE",   # Brenntag
    "CBK.DE",   # Commerzbank
    "CON.DE",   # Continental
    "DBK.DE",   # Deutsche Bank
    "DB1.DE",   # Deutsche Börse
    "DHL.DE",   # DHL Group
    "DTE.DE",   # Deutsche Telekom
    "EOAN.DE",  # E.ON
    "ENR.DE",   # Siemens Energy
    "FRE.DE",   # Fresenius
    "FME.DE",   # Fresenius Medical Care
    "HNR1.DE",  # Hannover Re
    "HEI.DE",   # Heidelberg Materials
    "HEN3.DE",  # Henkel
    "IFX.DE",   # Infineon Technologies
    "MBG.DE",   # Mercedes-Benz
    "MRK.DE",   # Merck KGaA
    "MTX.DE",   # MTU Aero Engines  ← 방산 (항공엔진)
    "MUV2.DE",  # Munich Re
    "P911.DE",  # Porsche AG
    "PAH3.DE",  # Porsche SE
    "QIA.DE",   # QIAGEN
    "RHM.DE",   # Rheinmetall  ← 방산 (지상 방산 1위)
    "RWE.DE",   # RWE
    "SAP.DE",   # SAP
    "SRT3.DE",  # Sartorius
    "SIE.DE",   # Siemens
    "SHL.DE",   # Siemens Healthineers
    "SY1.DE",   # Symrise
    "VOW3.DE",  # Volkswagen
    "VNA.DE",   # Vonovia
    "ZAL.DE",   # Zalando
    "DPW.DE",   # Deutsche Post (구 티커, DHL.DE와 병행)
]

# ── EU 섹터 집중 (방산 / 에너지 / 테크) ───────────────────────────────────────
# DAX 40에 없는 범유럽 종목만

EU_DEFENSE = [
    "BA.L",     # BAE Systems — 영국, 유럽 방산 최대
    "HO.PA",    # Thales — 프랑스, 전자전·사이버
    "SAF.PA",   # Safran — 프랑스, 항공엔진
    "HAG.DE",   # Hensoldt — 독일, 레이더·센서
    "LDO.MI",   # Leonardo — 이탈리아
]

EU_ENERGY = [
    "SHEL.L",   # Shell — 영국
    "BP.L",     # BP — 영국
    "TTE.PA",   # TotalEnergies — 프랑스
    "EQNR.OL",  # Equinor — 노르웨이 (전통+재생에너지)
    "ENI.MI",   # Eni — 이탈리아
    "ORSTED.CO",# Ørsted — 덴마크, 해상풍력 1위
]

EU_TECH = [
    "ASML.AS",  # ASML — 네덜란드, EUV 독점
    "STM.PA",   # STMicroelectronics — 프랑스, 반도체
    "DSY.PA",   # Dassault Systèmes — 프랑스, 산업 소프트웨어
    "CAP.PA",   # Capgemini — 프랑스, IT서비스
    "NOVN.SW",  # Novartis — 스위스
    "ROG.SW",   # Roche — 스위스
    "NESN.SW",  # Nestlé — 스위스
]

# ── 기본 유니버스 (미국) ───────────────────────────────────────────────────────
DEFAULT_UNIVERSE = US_LARGE_CAP + GROWTH_CANDIDATES

# 유럽 포함 확장 유니버스 (prescreener 입력용)
EU_UNIVERSE = DEFAULT_UNIVERSE + DAX40 + EU_DEFENSE + EU_ENERGY + EU_TECH

# 하위 호환성 유지
DE_STOCKS = DAX40
EU_STOCKS = EU_DEFENSE + EU_ENERGY + EU_TECH

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
RISK_VETO_CONFIDENCE = 0.80           # (deprecated) 하위호환용
RISK_SOFT_VETO_CONFIDENCE = 0.70      # 소프트 거부 (confidence 패널티만)
RISK_HARD_VETO_CONFIDENCE = 0.85      # 하드 거부 (RED_FLAG 격상)
RISK_SOFT_VETO_PENALTY = 0.15         # 소프트 거부 시 최종 confidence 감산

# ── 밸류에이션 드래그 ──────────────────────────────────────────────────────────
VALUATION_DRAG_CONFIDENCE = 0.60      # valuation-analyst PASS/AVOID 최소 confidence
VALUATION_DRAG_PENALTY = 0.10         # 최종 confidence 감산

# ── 데이터 수집 ─────────────────────────────────────────────────────────────
DEFAULT_LOOKBACK_DAYS = 90
MARKET_DATA_INTERVAL = "1d"
PEER_FETCH_TIMEOUT = 10  # 개별 피어 티커 요청 제한 시간 (초)

# ── 섹터별 대표 피어 티커 ──────────────────────────────────────────────────────
SECTOR_PEER_MAP: dict[str, list[str]] = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA"],
    "Financial Services": ["JPM", "BAC", "GS", "MS", "BRK-B"],
    "Healthcare": ["UNH", "JNJ", "LLY", "PFE", "ABBV"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "NKE", "MCD"],
    "Consumer Defensive": ["PG", "KO", "PEP", "COST", "WMT"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "Communication Services": ["GOOGL", "META", "DIS", "NFLX", "CMCSA"],
    "Industrials": ["CAT", "HON", "UNP", "GE", "RTX"],
}

# ── 섹터별 임계값 ──────────────────────────────────────────────────────────────
SECTOR_THRESHOLDS: dict[str, dict] = {
    "Technology": {
        "pe_low": 20, "pe_high": 35, "pe_extreme": 60,
        "gross_margin_good": 0.55, "op_margin_good": 0.20,
        "peer_gross_margin": 0.45,
    },
    "Financial Services": {
        "pe_low": 10, "pe_high": 18, "pe_extreme": 30,
        "gross_margin_good": 0.40, "op_margin_good": 0.25,
        "peer_gross_margin": 0.35,
    },
    "Healthcare": {
        "pe_low": 18, "pe_high": 30, "pe_extreme": 50,
        "gross_margin_good": 0.60, "op_margin_good": 0.15,
        "peer_gross_margin": 0.50,
    },
    "Consumer Cyclical": {
        "pe_low": 12, "pe_high": 25, "pe_extreme": 40,
        "gross_margin_good": 0.35, "op_margin_good": 0.10,
        "peer_gross_margin": 0.30,
    },
    "Consumer Defensive": {
        "pe_low": 15, "pe_high": 25, "pe_extreme": 35,
        "gross_margin_good": 0.35, "op_margin_good": 0.12,
        "peer_gross_margin": 0.30,
    },
    "Energy": {
        "pe_low": 8, "pe_high": 15, "pe_extreme": 25,
        "gross_margin_good": 0.30, "op_margin_good": 0.12,
        "peer_gross_margin": 0.25,
    },
    "Communication Services": {
        "pe_low": 15, "pe_high": 28, "pe_extreme": 45,
        "gross_margin_good": 0.50, "op_margin_good": 0.18,
        "peer_gross_margin": 0.40,
    },
    "Industrials": {
        "pe_low": 12, "pe_high": 22, "pe_extreme": 35,
        "gross_margin_good": 0.30, "op_margin_good": 0.10,
        "peer_gross_margin": 0.28,
    },
    "_default": {
        "pe_low": 15, "pe_high": 25, "pe_extreme": 40,
        "gross_margin_good": 0.50, "op_margin_good": 0.20,
        "peer_gross_margin": 0.35,
    },
}


def get_sector_thresholds(sector: str | None) -> dict:
    """섹터명으로 임계값 딕셔너리를 반환한다."""
    if sector and sector in SECTOR_THRESHOLDS:
        return SECTOR_THRESHOLDS[sector]
    return SECTOR_THRESHOLDS["_default"]


# ── 지터 (토론 다양성) ─────────────────────────────────────────────────────────
ENABLE_JITTER = True                   # False이면 모든 에이전트가 결정론적 (기존 동작)
JITTER_RANGE = 0.05                    # ±5% 범위로 임계값에 노이즈 부여

# ── 로깅 설정 ────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# ── 출력 설정 ────────────────────────────────────────────────────────────────
DEFAULT_OUTPUT_DIR = JOURNALS_DIR
CONSOLE_OUTPUT = True
