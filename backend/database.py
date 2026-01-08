"""
Database models and connection for AI Media Quality Validator.
Uses SQLite with aiosqlite for async operations.
"""

import aiosqlite
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "media_validator.db")


async def init_db():
    """Initialize the database with required tables."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                filepath TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                duration REAL,
                upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                overall_score REAL NOT NULL,
                video_score REAL,
                audio_score REAL,
                temporal_score REAL,
                raw_metrics TEXT,
                issues TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
            )
        """)
        
        await db.commit()


async def save_file_record(filename: str, filepath: str, file_size: int, duration: float = None) -> int:
    """Save a file record and return the file ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO files (filename, filepath, file_size, duration) VALUES (?, ?, ?, ?)",
            (filename, filepath, file_size, duration)
        )
        await db.commit()
        return cursor.lastrowid


async def save_analysis(
    file_id: int,
    overall_score: float,
    video_score: float,
    audio_score: float,
    temporal_score: float,
    raw_metrics: Dict[str, Any],
    issues: List[Dict[str, Any]]
) -> int:
    """Save analysis results and return the analysis ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO analyses 
               (file_id, overall_score, video_score, audio_score, temporal_score, raw_metrics, issues)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (file_id, overall_score, video_score, audio_score, temporal_score,
             json.dumps(raw_metrics), json.dumps(issues))
        )
        await db.commit()
        return cursor.lastrowid


async def get_analysis_by_file_id(file_id: int) -> Optional[Dict[str, Any]]:
    """Get analysis results for a file."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT a.*, f.filename, f.filepath, f.file_size, f.duration, f.upload_time
               FROM analyses a
               JOIN files f ON a.file_id = f.id
               WHERE a.file_id = ?
               ORDER BY a.created_at DESC LIMIT 1""",
            (file_id,)
        )
        row = await cursor.fetchone()
        if row:
            result = dict(row)
            result['raw_metrics'] = json.loads(result['raw_metrics']) if result['raw_metrics'] else {}
            result['issues'] = json.loads(result['issues']) if result['issues'] else []
            return result
        return None


async def get_file_history(limit: int = 20) -> List[Dict[str, Any]]:
    """Get recent file upload history with analysis scores."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT f.id, f.filename, f.file_size, f.duration, f.upload_time,
                      a.overall_score, a.video_score, a.audio_score
               FROM files f
               LEFT JOIN analyses a ON f.id = a.file_id
               ORDER BY f.upload_time DESC
               LIMIT ?""",
            (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_file_record(file_id: int) -> bool:
    """Delete a file record and its analysis."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("DELETE FROM files WHERE id = ?", (file_id,))
        await db.commit()
        return cursor.rowcount > 0


async def get_file_by_id(file_id: int) -> Optional[Dict[str, Any]]:
    """Get file record by ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM files WHERE id = ?",
            (file_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
