"""
Video Analysis Module for AI Media Quality Validator.
Analyzes video quality using BRISQUE, bitrate, resolution, and temporal stability metrics.
"""

import cv2
import numpy as np
import ffmpeg
import os
import tempfile
from typing import Dict, Any, List, Tuple
import subprocess
import json


class VideoAnalyzer:
    """Analyzes video files for quality metrics."""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.probe_data = None
        self.frames_analyzed = 0
        
    def analyze(self) -> Dict[str, Any]:
        """Run complete video analysis pipeline."""
        self.probe_data = self._probe_video()
        
        if not self.probe_data:
            return {"error": "Could not probe video file"}
        
        video_stream = self._get_video_stream()
        if not video_stream:
            return {"error": "No video stream found"}
        
        metrics = {
            "resolution": {
                "width": video_stream.get("width", 0),
                "height": video_stream.get("height", 0)
            },
            "bitrate": self._calculate_bitrate(),
            "codec": video_stream.get("codec_name", "unknown"),
            "fps": self._get_fps(video_stream),
            "duration": float(self.probe_data.get("format", {}).get("duration", 0)),
            "frame_count": int(video_stream.get("nb_frames", 0)) or self._estimate_frame_count(video_stream),
        }
        
        frame_analysis = self._analyze_frames()
        metrics.update(frame_analysis)
        
        temporal_analysis = self._analyze_temporal_stability(frame_analysis.get("frame_scores", []))
        metrics.update(temporal_analysis)
        
        issues = self._detect_issues(metrics)
        metrics["issues"] = issues
        
        return metrics

    def _probe_video(self) -> Dict[str, Any]:
        """Get video metadata using ffprobe."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_format", "-show_streams",
                    self.filepath
                ],
                capture_output=True,
                text=True
            )
            if not result.stdout:
                print(f"ffprobe failed to produce output for {self.filepath}. Error: {result.stderr}")
                return None
            return json.loads(result.stdout)
        except Exception as e:
            print(f"Exception during ffprobe for {self.filepath}: {str(e)}")
            return None
    
    def _get_video_stream(self) -> Dict[str, Any]:
        """Get the video stream from probe data."""
        if not self.probe_data:
            return None
        streams = self.probe_data.get("streams", [])
        for stream in streams:
            if stream.get("codec_type") == "video":
                return stream
        return None
    
    def _calculate_bitrate(self) -> int:
        """Calculate video bitrate in kbps."""
        if not self.probe_data:
            return 0
        
        format_data = self.probe_data.get("format", {})
        bit_rate = format_data.get("bit_rate")
        
        if bit_rate:
            return int(bit_rate) // 1000
        
        # Estimate from file size and duration
        size = int(format_data.get("size", 0))
        duration = float(format_data.get("duration", 1))
        if duration > 0:
            return int((size * 8) / duration / 1000)
        return 0
    
    def _get_fps(self, video_stream: Dict[str, Any]) -> float:
        """Extract FPS from video stream."""
        fps_str = video_stream.get("r_frame_rate", "30/1")
        try:
            num, den = map(int, fps_str.split("/"))
            return round(num / den, 2) if den else 30.0
        except:
            return 30.0
    
    def _estimate_frame_count(self, video_stream: Dict[str, Any]) -> int:
        """Estimate frame count from duration and FPS."""
        duration = float(self.probe_data.get("format", {}).get("duration", 0))
        fps = self._get_fps(video_stream)
        return int(duration * fps)

    def _analyze_frames(self) -> Dict[str, Any]:
        """Analyze sampled frames for quality using BRISQUE."""
        cap = cv2.VideoCapture(self.filepath)
        
        if not cap.isOpened():
            return {"brisque_score": 50, "frame_scores": [], "error": "Could not open video"}
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        duration = total_frames / fps if fps > 0 else 0
        
        # Sample frames: analyze 1 frame per second, max 60 frames
        sample_interval = max(1, int(fps))
        max_samples = min(60, int(duration) + 1)
        
        frame_scores = []
        brightness_values = []
        dark_frame_count = 0
        blocking_artifacts = []
        
        try:
            model_path = cv2.samples.findFile("brisque_model_live.yml", required=False)
            range_path = cv2.samples.findFile("brisque_range_live.yml", required=False)
            
            if model_path and range_path and os.path.exists(model_path) and os.path.exists(range_path):
                brisque = cv2.quality.QualityBRISQUE_create(model_path, range_path)
                use_brisque = True
            else:
                use_brisque = False
        except Exception as e:
            use_brisque = False
        
        frame_idx = 0
        samples_taken = 0
        
        while samples_taken < max_samples:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                break
            
            # Calculate quality score
            if use_brisque:
                try:
                    score = brisque.compute(frame)[0]
                    # BRISQUE: lower is better, typical range 0-100
                    normalized_score = max(0, min(100, 100 - score))
                except:
                    normalized_score = self._estimate_quality(frame)
            else:
                normalized_score = self._estimate_quality(frame)
            
            frame_scores.append({
                "frame": frame_idx,
                "timestamp": frame_idx / fps,
                "score": normalized_score
            })
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness = np.mean(gray)
            brightness_values.append(brightness)
            
            if brightness < 30:
                dark_frame_count += 1
                if self._detect_blocking(gray):
                    blocking_artifacts.append({
                        "timestamp": frame_idx / fps,
                        "frame": frame_idx
                    })
            
            frame_idx += sample_interval
            samples_taken += 1
            self.frames_analyzed = samples_taken
        
        cap.release()
        
        if frame_scores:
            scores = [f["score"] for f in frame_scores]
            avg_score = np.mean(scores)
            min_score = np.min(scores)
            score_std = np.std(scores)
        else:
            avg_score = 50
            min_score = 50
            score_std = 0
        
        return {
            "brisque_score": round(avg_score, 2),
            "min_quality_score": round(min_score, 2),
            "quality_variance": round(score_std, 2),
            "frame_scores": frame_scores,
            "dark_frame_ratio": dark_frame_count / max(1, samples_taken),
            "blocking_artifacts": blocking_artifacts,
            "avg_brightness": round(np.mean(brightness_values), 2) if brightness_values else 128
        }
    
    def _estimate_quality(self, frame: np.ndarray) -> float:
        """Estimate quality without BRISQUE using Laplacian variance (sharpness)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        # Normalize to 0-100 scale (empirically determined thresholds)
        if laplacian_var > 500:
            sharpness_score = 100
        elif laplacian_var > 100:
            sharpness_score = 60 + (laplacian_var - 100) / 10
        elif laplacian_var > 20:
            sharpness_score = 30 + (laplacian_var - 20) * 0.375
        else:
            sharpness_score = laplacian_var * 1.5
        
        noise_level = self._estimate_noise(gray)
        noise_penalty = min(20, noise_level * 2)
        
        return max(0, min(100, sharpness_score - noise_penalty))
    
    def _estimate_noise(self, gray: np.ndarray) -> float:
        """Estimate noise level in grayscale image."""
        blurred = cv2.medianBlur(gray, 3)
        diff = cv2.absdiff(gray, blurred)
        return np.mean(diff)
    
    def _detect_blocking(self, gray: np.ndarray) -> bool:
        """Detect blocking artifacts in an image."""
        h, w = gray.shape
        
        if h < 16 or w < 16:
            return False
        
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        
        block_size = 8
        x_blocks = np.abs(sobel_x[:, ::block_size]).mean()
        y_blocks = np.abs(sobel_y[::block_size, :]).mean()
        
        overall_x = np.abs(sobel_x).mean()
        overall_y = np.abs(sobel_y).mean()
        
        if overall_x > 0 and overall_y > 0:
            x_ratio = x_blocks / overall_x
            y_ratio = y_blocks / overall_y
            return x_ratio > 1.5 or y_ratio > 1.5
        
        return False
    
    def _analyze_temporal_stability(self, frame_scores: List[Dict]) -> Dict[str, Any]:
        """Analyze temporal stability from frame score variations."""
        if not frame_scores or len(frame_scores) < 2:
            return {
                "temporal_stability": 100,
                "frame_consistency": 100,
                "quality_drops": []
            }
        
        scores = [f["score"] for f in frame_scores]
        timestamps = [f["timestamp"] for f in frame_scores]
        
        diffs = np.abs(np.diff(scores))
        avg_diff = np.mean(diffs) if len(diffs) > 0 else 0
        
        stability = max(0, 100 - avg_diff * 3)
        
        quality_drops = []
        threshold = np.mean(scores) - 2 * np.std(scores) if np.std(scores) > 0 else np.mean(scores) - 10
        
        for i, (score, timestamp) in enumerate(zip(scores, timestamps)):
            if score < threshold:
                quality_drops.append({
                    "timestamp": round(timestamp, 2),
                    "score": round(score, 2),
                    "expected": round(np.mean(scores), 2)
                })
        
        mean_score = np.mean(scores)
        consistent_frames = sum(1 for s in scores if abs(s - mean_score) < 15)
        consistency = (consistent_frames / len(scores)) * 100
        
        return {
            "temporal_stability": round(stability, 2),
            "frame_consistency": round(consistency, 2),
            "quality_drops": quality_drops[:5]
        }
    
    def _detect_issues(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect video quality issues based on metrics."""
        issues = []
        
        width = metrics.get("resolution", {}).get("width", 0)
        height = metrics.get("resolution", {}).get("height", 0)
        
        if width < 640 or height < 360:
            issues.append({
                "type": "video",
                "severity": "high",
                "message": f"Low resolution detected: {width}x{height}",
                "recommendation": "The video looks quite pixelated. Using a higher resolution source will improve clarity."
            })
        elif width < 1280 or height < 720:
            issues.append({
                "type": "video",
                "severity": "medium",
                "message": f"Sub-HD resolution: {width}x{height}",
                "recommendation": "The video is below HD quality. Exporting in 720p or higher will make it look sharper."
            })
        
        bitrate = metrics.get("bitrate", 0)
        if bitrate < 1000:
            issues.append({
                "type": "video",
                "severity": "high",
                "message": f"Very low bitrate: {bitrate} kbps",
                "recommendation": "The video is heavily compressed. Increasing the bitrate will reduce visible artifacts."
            })
        elif bitrate < 2500:
            issues.append({
                "type": "video",
                "severity": "medium",
                "message": f"Low bitrate for resolution: {bitrate} kbps",
                "recommendation": "Some compression artifacts may be visible. A slightly higher bitrate can improve clarity."
            })
        
        brisque = metrics.get("brisque_score", 50)
        if brisque < 40:
            issues.append({
                "type": "video",
                "severity": "high",
                "message": f"Low visual quality score: {brisque:.1f}/100",
                "recommendation": "The video quality is noticeably degraded. Re-encoding with better settings may help."
            })
        elif brisque < 60:
            issues.append({
                "type": "video",
                "severity": "medium",
                "message": f"Below average visual quality: {brisque:.1f}/100",
                "recommendation": "The video looks slightly soft or compressed. Improving export settings can enhance quality."
            })
        
        blocking = metrics.get("blocking_artifacts", [])
        if len(blocking) > 3:
            timestamps = ", ".join([f"{b['timestamp']:.1f}s" for b in blocking[:3]])
            issues.append({
                "type": "video",
                "severity": "medium",
                "message": f"Blocking artifacts in dark scenes at: {timestamps}",
                "recommendation": "You may notice blocky patches in darker areas. Increasing bitrate or adjusting encoding can help."
            })
        
        stability = metrics.get("temporal_stability", 100)
        if stability < 60:
            issues.append({
                "type": "video",
                "severity": "medium",
                "message": f"Unstable quality: temporal stability {stability:.1f}%",
                "recommendation": "The video quality fluctuates over time. A more consistent encoding setting can smooth this out."
            })
        
        drops = metrics.get("quality_drops", [])
        if drops:
            drop_times = ", ".join([f"{d['timestamp']:.1f}s" for d in drops[:3]])
            issues.append({
                "type": "video",
                "severity": "low",
                "message": f"Quality drops detected at: {drop_times}",
                "recommendation": "There are brief moments where quality dips slightly, but overall playback remains acceptable."
            })

        return issues