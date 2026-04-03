import os
import uuid
import asyncio
import logging
import sys
from datetime import datetime
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, public, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("media_validator")

import numpy as np
import redis
import json

# Setup Redis for status tracking
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.from_url(REDIS_URL, decode_responses=True)

from worker import run_analysis_task

def convert_to_serializable(obj):
    """Recursively convert NumPy types to native Python types."""
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    elif isinstance(obj, (np.floating, float)):
        return float(obj)
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return convert_to_serializable(obj.tolist())
    elif isinstance(obj, dict):
        return {k: convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(item) for item in obj]
    return obj

from database import init_db, save_file_record, save_analysis, get_analysis_by_file_id, get_file_history, delete_file_record, get_file_by_id
from analyzers.video_analyzer import VideoAnalyzer
from analyzers.audio_analyzer import AudioAnalyzer
from analyzers.transcript_analyzer import TranscriptAnalyzer
from scoring.calculator import calculate_quality_score

# Application setup
app = FastAPI(
    title="AI Media Quality Validator",
    description="Deep AI analysis for video and audio quality assessment",
    version="1.0.0"
)

# Add No-Cache Middleware
app.add_middleware(NoCacheMiddleware)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Uploads directory
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Analysis status tracking
analysis_status = {}


class AnalysisStatus(BaseModel):
    """Analysis status response model."""
    file_id: int
    status: str  # pending, processing, completed, failed
    progress: int  # 0-100
    message: str


# Global analyzers initialized at startup
transcript_analyzer: Optional[TranscriptAnalyzer] = None

@app.on_event("startup")
async def startup_event():
    """Initialize database and heavy AI models on startup."""
    global transcript_analyzer
    await init_db()
    logger.info("Database initialized")
    
    # Pre-load heavy Whisper model once
    logger.info("Pre-loading TranscriptAnalyzer (Whisper large-v3)...")
    try:
        transcript_analyzer = TranscriptAnalyzer(model_size="large-v3")
        logger.info("TranscriptAnalyzer pre-loaded successfully")
    except Exception as e:
        logger.error(f"Failed to pre-load TranscriptAnalyzer: {e}")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    try:
        r.ping()
        redis_status = "connected"
    except Exception:
        redis_status = "disconnected"
        
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "redis": redis_status
    }


@app.post("/api/upload")
async def upload_file(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...),
    brand_name: Optional[str] = Form(None)
):
    """Upload a media file for analysis."""
    logger.info(f"Received upload request: {file.filename}")
    
    # Validate file type
    allowed_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.mp3', '.wav', '.flac', '.m4a', '.aac'}
    file_ext = Path(file.filename).suffix.lower()
    
    if file_ext not in allowed_extensions:
        logger.warning(f"Rejected file type: {file_ext}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Generate unique filename
    unique_id = str(uuid.uuid4())[:8]
    safe_filename = f"{unique_id}_{file.filename}"
    filepath = UPLOAD_DIR / safe_filename
    
    # Save file
    try:
        content = await file.read()
        file_size = len(content)
        logger.info(f"Saving file {safe_filename} ({file_size} bytes)")
        
        with open(filepath, "wb") as f:
            f.write(content)
        
        logger.info("File saved to disk")
        
        # Save to database
        file_id = await save_file_record(
            filename=file.filename,
            filepath=str(filepath),
            file_size=file_size
        )
        logger.info(f"File record saved with ID: {file_id}")
        
        # Initialize status in Redis
        status_data = {
            "status": "pending",
            "progress": 0,
            "message": "File uploaded, queued for analysis"
        }
        r.set(f"status:{file_id}", json.dumps(status_data), ex=3600)
        
        # Start analysis in Background (via Celery)
        logger.info(f"Dispatching Celery task for file {file_id}")
        run_analysis_task.delay(file_id, str(filepath), brand_name)
        
        return {
            "file_id": file_id,
            "filename": file.filename,
            "file_size": file_size,
            "status": "uploaded",
            "message": "File uploaded successfully, analysis queued..."
        }
        
    except Exception as e:
        logger.error(f"Error handling upload: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error saving file: {str(e)}")


@app.get("/api/status/{file_id}")
async def get_status(file_id: int):
    """Get analysis status for a file."""
    # Check Redis first (most recent status)
    status_json = r.get(f"status:{file_id}")
    if status_json:
        status_data = json.loads(status_json)
        return {
            "file_id": file_id,
            **status_data
        }
    
    # Check if analysis exists in database (completed long ago)
    analysis = await get_analysis_by_file_id(file_id)
    if analysis:
        return {
            "file_id": file_id,
            "status": "completed",
            "progress": 100,
            "message": "Analysis complete"
        }
    
    # Check if file exists but no status/analysis yet
    file_record = await get_file_by_id(file_id)
    if file_record:
        return {
            "file_id": file_id,
            "status": "pending",
            "progress": 0,
            "message": "Waiting in queue..."
        }
    
    raise HTTPException(status_code=404, detail="File not found")


@app.get("/api/analyze/{file_id}")
async def get_analysis(file_id: int):
    """Get analysis results for a file."""
    # Check if still processing via Redis
    status_json = r.get(f"status:{file_id}")
    if status_json:
        status_data = json.loads(status_json)
        if status_data["status"] == "processing" or status_data["status"] == "pending":
            return JSONResponse(
                status_code=202,
                content={
                    "file_id": file_id,
                    "status": status_data["status"],
                    "progress": status_data["progress"],
                    "message": status_data["message"]
                }
            )
        elif status_data["status"] == "failed":
            return JSONResponse(
                status_code=500,
                content={
                    "file_id": file_id,
                    "status": "failed",
                    "message": status_data["message"]
                }
            )
    
    # Get from database
    analysis = await get_analysis_by_file_id(file_id)
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Format response
    return {
        "file_id": file_id,
        "filename": analysis["filename"],
        "file_size": analysis["file_size"],
        "duration": analysis.get("duration"),
        "upload_time": analysis["upload_time"],
        "overall_score": analysis["overall_score"],
        "grade": get_grade(analysis["overall_score"]),
        "video_score": analysis["video_score"],
        "audio_score": analysis["audio_score"],
        "temporal_score": analysis["temporal_score"],
        "raw_metrics": analysis["raw_metrics"],
        "issues": analysis["issues"],
        "brand_compliance": analysis["raw_metrics"].get("brand_compliance", {}),
        "technical_specs": extract_technical_specs(analysis["raw_metrics"])
    }


def get_grade(score: float) -> str:
    """Get letter grade from score."""
    if score >= 90:
        return "A+"
    elif score >= 85:
        return "A"
    elif score >= 80:
        return "A-"
    elif score >= 75:
        return "B+"
    elif score >= 70:
        return "B"
    elif score >= 65:
        return "B-"
    elif score >= 60:
        return "C+"
    elif score >= 55:
        return "C"
    elif score >= 50:
        return "C-"
    elif score >= 45:
        return "D+"
    elif score >= 40:
        return "D"
    else:
        return "F"


def extract_technical_specs(raw_metrics: dict) -> dict:
    """Extract technical specifications from raw metrics."""
    video = raw_metrics.get("video", {})
    audio = raw_metrics.get("audio", {})
    
    resolution = video.get("resolution", {})
    
    return {
        "resolution": f"{resolution.get('width', 0)}x{resolution.get('height', 0)}",
        "bitrate_kbps": video.get("bitrate", 0),
        "codec": video.get("codec", "unknown"),
        "fps": video.get("fps", 0),
        "duration_seconds": video.get("duration", 0),
        "audio_sample_rate": audio.get("sample_rate", 0),
        "audio_channels": audio.get("channels", 0),
        "loudness_lufs": audio.get("loudness_lufs", 0)
    }


@app.get("/api/history")
async def get_history(limit: int = 20):
    """Get recent file analysis history."""
    history = await get_file_history(limit)
    
    # Add grades
    for item in history:
        if item.get("overall_score") is not None:
            item["grade"] = get_grade(item["overall_score"])
        else:
            item["grade"] = None
    
    return {"files": history}


@app.delete("/api/files/{file_id}")
async def delete_file(file_id: int):
    """Delete a file and its analysis."""
    # Get file record first
    file_record = await get_file_by_id(file_id)
    
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Delete physical file
    filepath = file_record.get("filepath")
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception:
            pass  # File may already be deleted
    
    # Delete from database
    deleted = await delete_file_record(file_id)
    
    if deleted:
        # Clean up status from Redis
        r.delete(f"status:{file_id}")
        return {"status": "deleted", "file_id": file_id}
    
    raise HTTPException(status_code=500, detail="Failed to delete file")


# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
    
    @app.get("/")
    async def serve_frontend():
        """Serve the frontend HTML."""
        from fastapi.responses import FileResponse
        return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6969)
