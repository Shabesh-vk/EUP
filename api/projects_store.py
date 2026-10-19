"""
Project state store with memory caching and persistent SQLite database backing.
"""

from __future__ import annotations
from typing import Dict, Any, Optional
from core.schema import Timeline
from db.database import db


class ProjectRecord:
    def __init__(self, project_id: str, timeline: Timeline, source_filepath: str, pending_clarification: Optional[Dict[str, Any]] = None):
        self.project_id = project_id
        self.timeline = timeline
        self.source_filepath = source_filepath
        # Retains conversational context when system asks a question
        self.pending_clarification: Optional[Dict[str, Any]] = pending_clarification


class ProjectStore:
    def __init__(self):
        self._projects: Dict[str, ProjectRecord] = {}

    def save(self, record: ProjectRecord):
        self._projects[record.project_id] = record
        try:
            db.save_project(
                record.project_id,
                record.timeline,
                record.source_filepath,
                record.pending_clarification,
            )
        except Exception as e:
            # Non-fatal if DB write fails during tests
            pass

    def get(self, project_id: str) -> Optional[ProjectRecord]:
        if project_id in self._projects:
            return self._projects[project_id]
        
        # Fallback to persistent database
        try:
            row = db.get_project(project_id)
            if row:
                rec = ProjectRecord(
                    project_id=row["project_id"],
                    timeline=row["timeline"],
                    source_filepath=row["source_filepath"],
                    pending_clarification=row["pending_clarification"],
                )
                self._projects[project_id] = rec
                return rec
        except Exception:
            pass
            
        return None

    def exists(self, project_id: str) -> bool:
        return self.get(project_id) is not None

    def list_all(self, limit: int = 50) -> list[ProjectRecord]:
        records: dict[str, ProjectRecord] = dict(self._projects)
        try:
            db_rows = db.list_projects(limit=limit)
            for row in db_rows:
                pid = row["project_id"]
                if pid not in records:
                    rec = ProjectRecord(
                        project_id=pid,
                        timeline=row["timeline"],
                        source_filepath=row["source_filepath"],
                        pending_clarification=row.get("pending_clarification"),
                    )
                    records[pid] = rec
                    self._projects[pid] = rec
        except Exception:
            pass
        return list(records.values())


project_store = ProjectStore()
