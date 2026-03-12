"""ExplorationDB 단위 테스트."""

import tempfile
from pathlib import Path

import pytest

from src.agents.models import (
    AgentOpinion,
    ExplorationResult,
    Signal,
    Urgency,
)
from src.storage.database import ExplorationDB


def _make_result(
    ticker: str = "AAPL",
    signal: Signal = Signal.BUY,
    confidence: float = 0.75,
    urgency: Urgency = Urgency.MAJORITY,
    timestamp: str = "2026-03-12T10:00:00",
) -> ExplorationResult:
    """테스트용 ExplorationResult를 생성한다."""
    opinions = [
        AgentOpinion(
            agent_name="fundamental-analyst",
            signal=Signal.BUY,
            confidence=0.80,
            rationale="Strong margins and cash flow",
        ),
        AgentOpinion(
            agent_name="risk-analyst",
            signal=Signal.WATCH,
            confidence=0.60,
            rationale="Moderate debt levels",
            risk_flags=["elevated D/E"],
        ),
    ]
    return ExplorationResult(
        ticker=ticker,
        company_name=f"{ticker} Corp",
        opinions=opinions,
        final_signal=signal,
        final_confidence=confidence,
        urgency=urgency,
        timestamp=timestamp,
    )


@pytest.fixture
def db(tmp_path):
    """임시 DB를 생성한다."""
    return ExplorationDB(db_path=tmp_path / "test.db")


class TestSaveAndRetrieve:
    def test_save_result_returns_id(self, db):
        result = _make_result()
        eid = db.save_result(result, report_path="/tmp/report.md")
        assert isinstance(eid, int)
        assert eid >= 1

    def test_get_history_returns_saved(self, db):
        db.save_result(_make_result(timestamp="2026-03-12T10:00:00"))
        db.save_result(_make_result(timestamp="2026-03-12T11:00:00"))

        history = db.get_history("AAPL")
        assert len(history) == 2
        # newest first
        assert history[0]["timestamp"] == "2026-03-12T11:00:00"

    def test_get_history_limit(self, db):
        for i in range(5):
            db.save_result(_make_result(timestamp=f"2026-03-{10+i:02d}T10:00:00"))
        history = db.get_history("AAPL", limit=3)
        assert len(history) == 3

    def test_get_history_filters_by_ticker(self, db):
        db.save_result(_make_result(ticker="AAPL"))
        db.save_result(_make_result(ticker="MSFT"))
        assert len(db.get_history("AAPL")) == 1
        assert len(db.get_history("MSFT")) == 1


class TestSignalChanges:
    def test_no_changes_returns_first_only(self, db):
        db.save_result(_make_result(signal=Signal.BUY, timestamp="2026-03-10T10:00:00"))
        db.save_result(_make_result(signal=Signal.BUY, timestamp="2026-03-11T10:00:00"))
        changes = db.get_signal_changes("AAPL")
        assert len(changes) == 1

    def test_detects_signal_change(self, db):
        db.save_result(_make_result(signal=Signal.WATCH, timestamp="2026-03-10T10:00:00"))
        db.save_result(_make_result(signal=Signal.BUY, timestamp="2026-03-11T10:00:00"))
        db.save_result(_make_result(signal=Signal.BUY, timestamp="2026-03-12T10:00:00"))
        db.save_result(_make_result(signal=Signal.STRONG_BUY, timestamp="2026-03-13T10:00:00"))
        changes = db.get_signal_changes("AAPL")
        assert len(changes) == 3
        assert changes[0]["final_signal"] == "watch"
        assert changes[1]["final_signal"] == "buy"
        assert changes[2]["final_signal"] == "strong_buy"

    def test_empty_ticker_returns_empty(self, db):
        assert db.get_signal_changes("NOPE") == []


class TestGetLatestAll:
    def test_returns_latest_per_ticker(self, db):
        db.save_result(_make_result(ticker="AAPL", signal=Signal.WATCH, timestamp="2026-03-10T10:00:00"))
        db.save_result(_make_result(ticker="AAPL", signal=Signal.BUY, timestamp="2026-03-11T10:00:00"))
        db.save_result(_make_result(ticker="MSFT", signal=Signal.STRONG_BUY, timestamp="2026-03-10T10:00:00"))

        latest = db.get_latest_all()
        assert len(latest) == 2
        aapl = next(r for r in latest if r["ticker"] == "AAPL")
        assert aapl["final_signal"] == "buy"


class TestSearch:
    def test_filter_by_min_signal(self, db):
        db.save_result(_make_result(signal=Signal.STRONG_BUY, timestamp="2026-03-10T10:00:00"))
        db.save_result(_make_result(signal=Signal.WATCH, timestamp="2026-03-11T10:00:00"))
        db.save_result(_make_result(signal=Signal.AVOID, timestamp="2026-03-12T10:00:00"))

        results = db.search(min_signal="buy")
        assert len(results) == 1
        assert results[0]["final_signal"] == "strong_buy"

        results = db.search(min_signal="watch")
        assert len(results) == 2

    def test_filter_by_min_confidence(self, db):
        db.save_result(_make_result(confidence=0.80, timestamp="2026-03-10T10:00:00"))
        db.save_result(_make_result(confidence=0.50, timestamp="2026-03-11T10:00:00"))

        results = db.search(min_confidence=0.70)
        assert len(results) == 1
        assert results[0]["final_confidence"] == 0.80

    def test_combined_filters(self, db):
        db.save_result(_make_result(signal=Signal.BUY, confidence=0.90, timestamp="2026-03-10T10:00:00"))
        db.save_result(_make_result(signal=Signal.BUY, confidence=0.50, timestamp="2026-03-11T10:00:00"))
        db.save_result(_make_result(signal=Signal.AVOID, confidence=0.90, timestamp="2026-03-12T10:00:00"))

        results = db.search(min_signal="buy", min_confidence=0.70)
        assert len(results) == 1
        assert results[0]["final_signal"] == "buy"
        assert results[0]["final_confidence"] == 0.90

    def test_no_filters_returns_all(self, db):
        db.save_result(_make_result(timestamp="2026-03-10T10:00:00"))
        db.save_result(_make_result(timestamp="2026-03-11T10:00:00"))
        assert len(db.search()) == 2


class TestAgentOpinions:
    def test_opinions_saved(self, db):
        result = _make_result()
        eid = db.save_result(result)

        # Verify opinions via direct query
        with db._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_opinions WHERE exploration_id = ?", (eid,)
            ).fetchall()
        assert len(rows) == 2
        names = {r["agent_name"] for r in rows}
        assert "fundamental-analyst" in names
        assert "risk-analyst" in names


class TestEdgeCases:
    def test_empty_db_methods(self, db):
        assert db.get_history("NOPE") == []
        assert db.get_signal_changes("NOPE") == []
        assert db.get_latest_all() == []
        assert db.search() == []

    def test_report_path_none(self, db):
        eid = db.save_result(_make_result())
        history = db.get_history("AAPL")
        assert history[0]["report_path"] is None
