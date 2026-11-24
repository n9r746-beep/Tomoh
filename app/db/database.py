"""
Dual-engine database adapter:
  - Production: PostgreSQL (`postgresql://...` via psycopg2/psycopg)
  - Local Dev / Tests: SQLite (`sqlite:///...` via builtin sqlite3)
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional, Sequence


class Database:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._transaction_connection = ContextVar("tomoh_transaction", default=None)
        if database_url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            self.sqlite_path = database_url[len("sqlite:///") :]
        elif database_url.startswith("postgresql://") or database_url.startswith("postgres://"):
            self.dialect = "postgresql"
            self.sqlite_path = None
        else:
            raise ValueError(f"Unsupported database URL scheme: {database_url}")

    @contextmanager
    def connection(self) -> Iterator[Any]:
        current = self._transaction_connection.get()
        if current is not None:
            yield current
            return
        if self.dialect == "sqlite":
            conn = sqlite3.connect(self.sqlite_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        else:
            try:
                import psycopg2  # type: ignore
                import psycopg2.extras  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL driver (psycopg2) is not installed in this environment."
                ) from exc
            conn = psycopg2.connect(self.database_url, cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=10)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @contextmanager
    def transaction(self):
        if self._transaction_connection.get() is not None:
            yield
            return
        with self.connection() as conn:
            if self.dialect == "sqlite":
                conn.execute("BEGIN IMMEDIATE")
            token = self._transaction_connection.set(conn)
            try:
                yield
            finally:
                self._transaction_connection.reset(token)

    def lock_reporting_week(self, week_id):
        suffix = " FOR UPDATE" if self.dialect == "postgresql" else ""
        return self.fetch_one("SELECT * FROM reporting_weeks WHERE id = ?" + suffix, (week_id,))

    def _adapt_sql(self, sql: str) -> str:
        if self.dialect == "postgresql":
            return sql.replace("?", "%s")
        return sql

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            cur = conn.cursor()
            cur.execute(self._adapt_sql(sql), params)
            rows = cur.fetchall()
            return [{k: (v.isoformat() if isinstance(v, (date, datetime)) else float(v) if isinstance(v, Decimal) else v) for k, v in dict(r).items()} for r in rows]

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            cur = conn.cursor()
            cur.execute(self._adapt_sql(sql), params)
            row = cur.fetchone()
            return {k: (v.isoformat() if isinstance(v, (date, datetime)) else float(v) if isinstance(v, Decimal) else v) for k, v in dict(row).items()} if row is not None else None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.connection() as conn:
            cur = conn.cursor()
            cur.execute(self._adapt_sql(sql), params)
            return cur.rowcount

    def execute_script(self, script_sql: str) -> None:
        with self.connection() as conn:
            if self.dialect == "sqlite":
                conn.executescript(script_sql)
            else:
                cur = conn.cursor()
                cur.execute(script_sql)
