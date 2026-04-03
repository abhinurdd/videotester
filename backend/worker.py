import os
import asyncio
import logging
import gc
import json
import redis
import numpy as np
from celery import Celery
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("media_validator.worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.from_url(REDIS_URL)

celery = Celery(
    'tasks',
    broker=REDIS_URL,
    backend=REDIS_URL
)

from analyzers.video_analyzer import VideoAnalyzer
from analyzers.audio_analyzer import AudioAnalyzer
from analyzers.transcript_analyzer import TranscriptAnalyzer
from scoring.calculator import calculate_quality_score
from database import save_analysis, get_file_by_id

transcript_analyzer = None

def get_analyzer():
    """Lazily load the Whisper model once per worker process."""
    global transcript_analyzer
    if transcript_analyzer is None:
        logger.info("Worker: Loading TranscriptAnalyzer (Whisper large-v3)...")
        transcript_analyzer = TranscriptAnalyzer(model_size="large-v3")
        logger.info("Worker: Model loaded successfully.")
    return transcript_analyzer

def update_status(file_id, status, progress, message):
    """Update analysis status in Redis for retrieval by the API."""
    data = {
        "status": status,
        "progress": progress,
        "message": message
    }
    r.set(f"status:{file_id}", json.dumps(data), ex=3600) # Expire in 1 hour
    logger.info(f"Status Updated [{file_id}]: {status} - {progress}% - {message}")

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

@celery.task(name="run_analysis_task")
def run_analysis_task(file_id: int, filepath: str, brand_name: Optional[str] = None):
    """Celery task to run video and audio analysis."""
    loop = asyncio.get_event_loop()
    
    logger.info(f"Task Started for file {file_id}")
    try:
        update_status(file_id, "processing", 10, "Analyzing video...")
        
        # Step 1: Video Analysis
        video_analyzer = VideoAnalyzer(filepath)
        video_metrics = video_analyzer.analyze()
        
        update_status(file_id, "processing", 30, "Analyzing audio...")
        
        # Step 2: Audio Analysis
        audio_analyzer = AudioAnalyzer(filepath)
        audio_metrics = audio_analyzer.analyze()
        
        update_status(file_id, "processing", 60, "Transcribing & checking brand...")
        
        # Step 3: Brand Compliance
        brand_compliance = {}
        if brand_name:
            try:
                analyzer = get_analyzer()
                segments = analyzer.transcribe_audio(filepath, brand_hint=brand_name)
                brand_result = analyzer.count_brand_mentions(segments, brand_name)
                brand_compliance = brand_result
            except Exception as e:
                logger.error(f"Brand check failed: {e}")
                brand_compliance = {"error": str(e)}

        update_status(file_id, "processing", 90, "Finalizing scores...")
        
        # Step 4: Scoring
        score_result = calculate_quality_score(video_metrics, audio_metrics)
        
        # Build raw metrics
        raw_metrics = {
            "video": video_metrics,
            "audio": audio_metrics
        }
        if brand_compliance:
            raw_metrics["brand_compliance"] = brand_compliance

        # Sanitize data
        score_result = convert_to_serializable(score_result)
        raw_metrics = convert_to_serializable(raw_metrics)
        
        # Step 5: Save to Database (Awaiting because it's async)
        loop.run_until_complete(save_analysis(
            file_id=file_id,
            overall_score=score_result["overall_score"],
            video_score=score_result["video_score"],
            audio_score=score_result["audio_score"],
            temporal_score=score_result.get("temporal_score", 0),
            raw_metrics=raw_metrics,
            issues=score_result["issues"]
        ))
        
        update_status(file_id, "completed", 100, "Analysis complete")
        
    except Exception as e:
        logger.error(f"Task Failed for file {file_id}: {str(e)}", exc_info=True)
        update_status(file_id, "failed", 0, f"Analysis failed: {str(e)}")
        
    finally:
        # Cleanup
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Deleted source file: {filepath}")
        except Exception:
            pass

if __name__ == "__main__":
    celery.worker_main(['worker', '--loglevel=info', '--pool=solo'])
