"""
Persistent relational database layer for IncuBrix.
Provides ACID persistence for Projects, Idempotency records, and Jobs.
Uses SQLite for embedded local storage and automated test reproducibility,
with full PostgreSQL schema compatibility.
"""

from __future__ import annotations
import json
import os
import sqlite3
import threading
import time
from typing import Dict, Any, Optional, List
from core.schema import Timeline


class DatabaseManager:
    """Thread-safe SQLite database manager for persistent state."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            storage_dir = os.environ.get("STORAGE_DIR", "storage_data")
            os.makedirs(storage_dir, exist_ok=True)
            db_path = os.path.join(storage_dir, "incubrix.db")
        self.db_path = os.path.abspath(db_path)
        self._lock = threading.Lock()
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                # Projects table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS projects (
                        project_id TEXT PRIMARY KEY,
                        timeline_json TEXT NOT NULL,
                        source_filepath TEXT NOT NULL,
                        pending_clarification_json TEXT,
                        updated_at REAL NOT NULL
                    )
                """)
                # Idempotency records table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS idempotency (
                        key TEXT PRIMARY KEY,
                        body_hash TEXT NOT NULL,
                        status_code INTEGER,
                        response_json TEXT,
                        job_id TEXT,
                        created_at REAL NOT NULL
                    )
                """)
                # Jobs table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_id TEXT PRIMARY KEY,
                        job_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        progress INTEGER NOT NULL,
                        result_json TEXT,
                        error_json TEXT,
                        created_at REAL NOT NULL,
                        completed_at REAL
                    )
                """)
                # Chat messages table (persists conversational assistant history per project)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chat_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        metadata_json TEXT,
                        created_at REAL NOT NULL
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_proj ON chat_messages(project_id)")
                # Authoritative conversation context table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS conversation_contexts (
                        project_id TEXT PRIMARY KEY,
                        context_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)
                conn.commit()
            finally:
                conn.close()

    # --- Projects API ---
    def save_project(self, project_id: str, timeline: Timeline, source_filepath: str, pending_clarification: Optional[Dict[str, Any]] = None):
        t_json = timeline.model_dump_json()
        p_json = json.dumps(pending_clarification) if pending_clarification else None
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO projects (project_id, timeline_json, source_filepath, pending_clarification_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(project_id) DO UPDATE SET
                        timeline_json=excluded.timeline_json,
                        source_filepath=excluded.source_filepath,
                        pending_clarification_json=excluded.pending_clarification_json,
                        updated_at=excluded.updated_at
                """, (project_id, t_json, source_filepath, p_json, now))
                conn.commit()
            finally:
                conn.close()

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    "project_id": row["project_id"],
                    "timeline": Timeline.model_validate_json(row["timeline_json"]),
                    "source_filepath": row["source_filepath"],
                    "pending_clarification": json.loads(row["pending_clarification_json"]) if row["pending_clarification_json"] else None,
                    "updated_at": row["updated_at"],
                }
            finally:
                conn.close()

    def list_projects(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT project_id, timeline_json, source_filepath, pending_clarification_json, updated_at FROM projects ORDER BY updated_at DESC LIMIT ?", (limit,))
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    try:
                        results.append({
                            "project_id": row["project_id"],
                            "timeline": Timeline.model_validate_json(row["timeline_json"]),
                            "source_filepath": row["source_filepath"],
                            "pending_clarification": json.loads(row["pending_clarification_json"]) if row["pending_clarification_json"] else None,
                            "updated_at": row["updated_at"],
                        })
                    except Exception:
                        pass
                return results
            finally:
                conn.close()

    # --- Idempotency API ---
    def get_idempotency_record(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM idempotency WHERE key = ?", (key,))
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    "key": row["key"],
                    "body_hash": row["body_hash"],
                    "status_code": row["status_code"],
                    "response_data": json.loads(row["response_json"]) if row["response_json"] else None,
                    "job_id": row["job_id"],
                }
            finally:
                conn.close()

    def register_idempotency_key(self, key: str, body_hash: str):
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO idempotency (key, body_hash, created_at)
                    VALUES (?, ?, ?)
                """, (key, body_hash, now))
                conn.commit()
            finally:
                conn.close()

    def record_idempotency_response(self, key: str, status_code: int, response_data: Dict[str, Any], job_id: Optional[str] = None):
        r_json = json.dumps(response_data)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE idempotency SET status_code = ?, response_json = ?, job_id = ?
                    WHERE key = ?
                """, (status_code, r_json, job_id, key))
                conn.commit()
            finally:
                conn.close()

    # --- Jobs API ---
    def save_job(self, job_id: str, job_type: str, status: str, progress: int, created_at: float,
                 result: Optional[Dict[str, Any]] = None, error: Optional[Dict[str, Any]] = None, completed_at: Optional[float] = None):
        res_json = json.dumps(result) if result else None
        err_json = json.dumps(error) if error else None
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO jobs (job_id, job_type, status, progress, result_json, error_json, created_at, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        status=excluded.status,
                        progress=excluded.progress,
                        result_json=excluded.result_json,
                        error_json=excluded.error_json,
                        completed_at=excluded.completed_at
                """, (job_id, job_type, status, progress, res_json, err_json, created_at, completed_at))
                conn.commit()
            finally:
                conn.close()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    "job_id": row["job_id"],
                    "job_type": row["job_type"],
                    "status": row["status"],
                    "progress": row["progress"],
                    "result": json.loads(row["result_json"]) if row["result_json"] else None,
                    "error": json.loads(row["error_json"]) if row["error_json"] else None,
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"],
                }
            finally:
                conn.close()

    # --- Chat & Context Persistence ---
    def save_chat_message(
        self,
        project_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        meta_json = json.dumps(metadata) if metadata else None
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO chat_messages (project_id, role, content, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (project_id, role, content, meta_json, now))
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_chat_history(self, project_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM chat_messages 
                    WHERE project_id = ? 
                    ORDER BY id ASC 
                    LIMIT ?
                """, (project_id, limit))
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    results.append({
                        "id": r["id"],
                        "project_id": r["project_id"],
                        "role": r["role"],
                        "content": r["content"],
                        "metadata": json.loads(r["metadata_json"]) if r["metadata_json"] else None,
                        "created_at": r["created_at"],
                    })
                return results
            finally:
                conn.close()

    def save_conversation_context(self, project_id: str, context: Dict[str, Any]):
        ctx_json = json.dumps(context)
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO conversation_contexts (project_id, context_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(project_id) DO UPDATE SET
                        context_json=excluded.context_json,
                        updated_at=excluded.updated_at
                """, (project_id, ctx_json, now))
                conn.commit()
            finally:
                conn.close()

    def get_conversation_context(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT context_json FROM conversation_contexts WHERE project_id = ?", (project_id,))
                row = cursor.fetchone()
                if row and row["context_json"]:
                    return json.loads(row["context_json"])
                return None
            finally:
                conn.close()


# Global DB instance
db = DatabaseManager()
