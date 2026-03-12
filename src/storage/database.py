"""SQLite-based exploration result storage.

분석 결과를 queryable DB에 저장하여 시그널 변화 추적 등을 지원한다.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.agents.models import ExplorationResult, Signal


_SCHEMA = """
CREATE TABLE IF NOT EXISTS explorations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    company_name TEXT NOT NULL,
    final_signal TEXT NOT NULL,
    final_confidence REAL NOT NULL,
    urgency TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    report_path TEXT
);

CREATE TABLE IF NOT EXISTS agent_opinions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exploration_id INTEGER NOT NULL,
    agent_name TEXT NOT NULL,
    signal TEXT NOT NULL,
    confidence REAL NOT NULL,
    rationale TEXT NOT NULL,
    FOREIGN KEY (exploration_id) REFERENCES explorations(id)
);

CREATE INDEX IF NOT EXISTS idx_explorations_ticker ON explorations(ticker);
CREATE INDEX IF NOT EXISTS idx_explorations_timestamp ON explorations(timestamp);
CREATE INDEX IF NOT EXISTS idx_agent_opinions_exploration ON agent_opinions(exploration_id);
"""

# Signal ordering for search filtering (lower index = more bullish)
_SIGNAL_ORDER = [
    Signal.STRONG_BUY,
    Signal.BUY,
    Signal.WATCH,
    Signal.PASS,
    Signal.AVOID,
]


class ExplorationDB:
    """SQLite database for storing and querying exploration results."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            from src.utils.config import DB_PATH
            db_path = DB_PATH
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_tables(self) -> None:
        """Auto-create tables on first use."""
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def save_result(
        self, result: ExplorationResult, report_path: str | None = None
    ) -> int:
        """Save an exploration result and all agent opinions.

        Returns the exploration id.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO explorations
                    (ticker, company_name, final_signal, final_confidence,
                     urgency, timestamp, report_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.ticker,
                    result.company_name,
                    result.final_signal.value,
                    result.final_confidence,
                    result.urgency.value,
                    result.timestamp,
                    report_path,
                ),
            )
            exploration_id = cursor.lastrowid

            for opinion in result.opinions:
                conn.execute(
                    """
                    INSERT INTO agent_opinions
                        (exploration_id, agent_name, signal, confidence, rationale)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        exploration_id,
                        opinion.agent_name,
                        opinion.signal.value,
                        opinion.confidence,
                        opinion.rationale,
                    ),
                )

            return exploration_id

    def get_history(self, ticker: str, limit: int = 10) -> list[dict]:
        """Recent explorations for a ticker, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, ticker, company_name, final_signal, final_confidence,
                       urgency, timestamp, report_path
                FROM explorations
                WHERE ticker = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (ticker.upper(), limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_signal_changes(self, ticker: str) -> list[dict]:
        """Return only entries where the signal changed from the previous one."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, ticker, company_name, final_signal, final_confidence,
                       urgency, timestamp, report_path
                FROM explorations
                WHERE ticker = ?
                ORDER BY timestamp ASC
                """,
                (ticker.upper(),),
            ).fetchall()

        if not rows:
            return []

        changes = [dict(rows[0])]
        prev_signal = rows[0]["final_signal"]
        for row in rows[1:]:
            if row["final_signal"] != prev_signal:
                changes.append(dict(row))
                prev_signal = row["final_signal"]
        return changes

    def get_latest_all(self) -> list[dict]:
        """Latest exploration for each ticker."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.id, e.ticker, e.company_name, e.final_signal,
                       e.final_confidence, e.urgency, e.timestamp, e.report_path
                FROM explorations e
                INNER JOIN (
                    SELECT ticker, MAX(timestamp) AS max_ts
                    FROM explorations
                    GROUP BY ticker
                ) latest ON e.ticker = latest.ticker AND e.timestamp = latest.max_ts
                ORDER BY e.ticker
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def search(
        self,
        min_signal: str | None = None,
        min_confidence: float | None = None,
    ) -> list[dict]:
        """Filter explorations by signal level and/or minimum confidence.

        min_signal filters to that signal or more bullish (e.g. "buy" includes
        "strong_buy" and "buy").
        """
        conditions = []
        params: list = []

        if min_signal is not None:
            try:
                threshold = Signal(min_signal.lower())
            except ValueError:
                threshold = None

            if threshold is not None:
                cutoff_idx = _SIGNAL_ORDER.index(threshold)
                allowed = [s.value for s in _SIGNAL_ORDER[: cutoff_idx + 1]]
                placeholders = ", ".join("?" for _ in allowed)
                conditions.append(f"final_signal IN ({placeholders})")
                params.extend(allowed)

        if min_confidence is not None:
            conditions.append("final_confidence >= ?")
            params.append(min_confidence)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT id, ticker, company_name, final_signal, final_confidence,
                   urgency, timestamp, report_path
            FROM explorations
            {where}
            ORDER BY timestamp DESC
        """

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
