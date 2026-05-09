import os
import asyncio
import logging
import gc
import shutil
import json
import redis
from redis.retry import Retry
from redis.backoff import ExponentialBackoff
import numpy as np
from celery import Celery
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("media_validator.worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Synchronous retry strategy for connection resets
retry_strategy = Retry(ExponentialBackoff(), 3)

# Limit connections per worker process and add health checks
pool = redis.ConnectionPool.from_url(
    REDIS_URL, 
    max_connections=5, 
    health_check_interval=30,
    socket_connect_timeout=5,
    socket_keepalive=True,
    retry_on_timeout=True
)
r = redis.Redis(
    connection_pool=pool, 
    retry=retry_strategy, 
    retry_on_timeout=True
)

celery = Celery(
    'tasks',
    broker=REDIS_URL,
    backend=REDIS_URL
)

# Optimize Celery connection usage
celery.conf.update(
    broker_pool_limit=10,        # Limit number of connections to Redis broker
    redis_max_connections=10,    # Limit connections to Redis backend
    result_persistent=False,     # Don't persist results (using manual status tracking anyway)
    broker_transport_options={
        'visibility_timeout': 3600,
        'sep': ':',
    }
)

from analyzers.video_analyzer import VideoAnalyzer
from analyzers.audio_analyzer import AudioAnalyzer
from analyzers.transcript_analyzer import TranscriptAnalyzer
from analyzers.image_analyzer import ImageAnalyzer
from scoring.calculator import calculate_quality_score
from database import save_analysis, get_file_by_id

transcript_analyzer = None

def get_analyzer():
    """Lazily load the TranscriptAnalyzer (using Groq API)."""
    global transcript_analyzer
    if transcript_analyzer is None:
        logger.info("Worker: Initializing TranscriptAnalyzer (Groq API)...")
        transcript_analyzer = TranscriptAnalyzer()
        logger.info("Worker: Analyzer initialized successfully.")
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
def run_analysis_task(file_id: int, filepath: str, brand_name: Optional[str] = None, r2_url: Optional[str] = None, callback_url: Optional[str] = None, content_type: Optional[str] = None, **kwargs):
    """Celery task to run video and audio analysis."""
    loop = asyncio.get_event_loop()
    
    logger.info(f"Task Started for file {file_id}")
    
    # Pre-flight check for dependencies
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        error_msg = "FFmpeg/FFprobe not found in PATH! Analysis cannot proceed."
        logger.critical(error_msg)
        update_status(file_id, "failed", 0, error_msg)
        return
    
    try:
        # Step 0: Download from R2 if URL provided
        if r2_url:
            update_status(file_id, "processing", 5, "Downloading from R2...")
            from r2_utils import download_from_url
            if not download_from_url(r2_url, filepath):
                raise Exception("Failed to download file from R2")
            
            # Update file size in database
            file_size = os.path.getsize(filepath)
            logger.info(f"File downloaded successfully. Size: {file_size} bytes")
            
            # Update file record in DB
            from database import save_file_record # It's actually update, but we'll use a raw query or just leave it for now
            # For now, just log it. The main issue is the analysis.
        
        is_video = True
        ext = os.path.splitext(filepath)[1].lower()
        
        video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.mpeg', '.mpg', '.3gp', '.m4v'}
        image_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.heic', '.heif'}

        if content_type:
            ct = content_type.lower()
            if ct in ['reel', 'reels', 'short', 'shorts']:
                is_video = True
            elif ct in ['post', 'posts']:
                is_video = False
            elif ct in ['story', 'stories']:
                # Auto-detect by extension
                is_video = ext in video_exts
        else:
            # Full auto-detect
            is_video = ext in video_exts or ext not in image_exts

        final_payload = {}

        if is_video:
            update_status(file_id, "processing", 15, "Analyzing video...")
            # Step 1: Video Analysis
            video_analyzer = VideoAnalyzer(filepath)
            video_metrics = video_analyzer.analyze()
            
            update_status(file_id, "processing", 40, "Analyzing audio...")
            # Step 2: Audio Analysis
            audio_analyzer = AudioAnalyzer(filepath)
            audio_metrics = audio_analyzer.analyze()
            
            update_status(file_id, "processing", 70, "Transcribing & checking brand via Groq...")
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
                    brand_compliance = {
                        "target_brand": brand_name,
                        "error": str(e),
                        "mention_count": 0,
                        "timestamps": [],
                        "full_transcript": []
                    }

            # Step 4: Scoring (Legacy Video Format)
            score_result = calculate_quality_score(video_metrics, audio_metrics)
            
            # Unify for Response
            res = video_metrics.get("resolution", {})
            w, h = res.get("width", 0), res.get("height", 0)
            aspect_ratio = round(w / h, 2) if h > 0 else 0
            
            orientation = "square"
            if aspect_ratio > 1.1: orientation = "landscape"
            elif aspect_ratio < 0.9: orientation = "portrait"

            final_payload = {
                "audio": audio_metrics,
                "video": video_metrics, # Keep video specific metrics
                "brand_compliance": {
                    "summary": f"Video analysis for {brand_name}",
                    "transcript": " ".join([s.get("text", "") for s in (brand_compliance.get("full_transcript", []))]) if brand_compliance else "",
                    "target_brand": brand_name,
                    "mention_count": brand_compliance.get("mention_count", 0),
                    "logo_visibility": "none" # Video analyzer currently doesn't do logos
                },
                "technical_status": {
                    "short_side": min(w, h),
                    "is_high_res": 1 if min(w, h) >= 720 else 0,
                    "orientation": orientation,
                    "aspect_ratio": aspect_ratio,
                    "resolution_label": f"{min(w, h)}p",
                    "actual_resolution": f"{w}x{h}",
                    "safe_area_warning": 0,
                    "aspect_ratio_message": f"Suitable for {content_type or 'video'}.",
                    "content_type_validated": content_type or ("reels" if orientation == "portrait" else "posts")
                }
            }
        else:
            update_status(file_id, "processing", 30, "Analyzing image content...")
            # Step 1: Image Analysis
            image_analyzer = ImageAnalyzer()
            final_payload = image_analyzer.analyze(filepath, target_brand=brand_name)
            
            # Step 2: Scoring (Synthetic for images)
            score_result = {
                "overall_score": final_payload["image"]["content"]["image_vibrancy_score"],
                "video_score": final_payload["image"]["content"]["image_vibrancy_score"],
                "audio_score": 0,
                "issues": []
            }
            if final_payload["image"]["sharpness_score"] < 50:
                score_result["issues"].append({"type": "image", "severity": "medium", "message": "Low image sharpness"})

        # Finalize
        update_status(file_id, "processing", 90, "Finalizing results...")
        
        # Sanitize data
        final_payload = convert_to_serializable(final_payload)
        score_result = convert_to_serializable(score_result)
        
        # Step 5: Save to Database
        loop.run_until_complete(save_analysis(
            file_id=file_id,
            overall_score=score_result["overall_score"],
            video_score=score_result["video_score"],
            audio_score=score_result["audio_score"],
            temporal_score=score_result.get("temporal_score", 0),
            raw_metrics=final_payload, # Save the unified payload
            issues=score_result["issues"]
        ))
        
        update_status(file_id, "completed", 100, "Analysis complete")
        
        # Step 6: Trigger Callback
        base_url = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
        default_callback = f"{base_url}/api/v2/creators/campaigns/analysis-callback"
        target_callback = callback_url or default_callback
        
        try:
            import requests
            metadata = kwargs.get("metadata", {})
            
            callback_data = {
                "file_id": file_id,
                "campaign_id": metadata.get("campaign_id"),
                "creator_id": metadata.get("creator_id"),
                "status": "completed",
                "overall_score": score_result["overall_score"],
                "video_score": score_result["video_score"],
                "audio_score": score_result["audio_score"],
                "temporal_score": score_result.get("temporal_score", 0),
                "raw_metrics": final_payload,
                "issues": score_result["issues"],
                "metadata": metadata
            }
            
            logger.info(f"Triggering callback to: {target_callback}")
            response = requests.post(target_callback, json=callback_data, timeout=30)
            response.raise_for_status()
            logger.info("Callback successful")
        except Exception as cb_e:
            logger.error(f"Callback failed to {target_callback}: {cb_e}")
        
    except Exception as e:
        logger.error(f"Task Failed for file {file_id}: {str(e)}", exc_info=True)
        update_status(file_id, "failed", 0, f"Analysis failed: {str(e)}")
        
    finally:
        # Cleanup
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Deleted temporary file: {filepath}")
        except Exception:
            pass

if __name__ == "__main__":
    # Increased concurrency to 50 as requested
    # Using 'prefork' or 'gevent' for high concurrency. 
    # 'prefork' is better for CPU tasks, 'gevent' for IO.
    # Given the 50 concurrent requirement, we'll use prefork with 50 workers.
    celery.worker_main(['worker', '--loglevel=info', '--concurrency=50', '--pool=prefork'])
