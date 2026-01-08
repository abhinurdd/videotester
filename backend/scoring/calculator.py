"""
Scoring Calculator for AI Media Quality Validator.
Calculates weighted quality scores from video and audio analysis results.
"""

from typing import Dict, Any, List


class QualityScorer:
    """Calculates overall quality score from video and audio metrics."""
    
    # Scoring weights
    VIDEO_WEIGHT = 0.50  # 50%
    AUDIO_WEIGHT = 0.50  # 50%
    TEMPORAL_WEIGHT = 0.00  # 0% (Disabled)
    
    # Video sub-weights
    VIDEO_QUALITY_WEIGHT = 0.50  # BRISQUE score
    VIDEO_BITRATE_WEIGHT = 0.30  # Bitrate score
    VIDEO_RESOLUTION_WEIGHT = 0.20  # Resolution score
    
    # Audio sub-weights
    AUDIO_SNR_WEIGHT = 0.30  # SNR score
    AUDIO_CLARITY_WEIGHT = 0.40  # Speech clarity
    AUDIO_CLIPPING_WEIGHT = 0.30  # No-clipping score
    
    def __init__(self, video_metrics: Dict[str, Any], audio_metrics: Dict[str, Any]):
        self.video_metrics = video_metrics
        self.audio_metrics = audio_metrics
    
    def calculate(self) -> Dict[str, Any]:
        """Calculate complete quality assessment."""
        # Calculate individual scores
        video_score = self._calculate_video_score()
        audio_score = self._calculate_audio_score()
        temporal_score = self._calculate_temporal_score() # Still calculate, but won't contribute to overall
        
        # Calculate weighted overall score
        overall_score = (
            video_score * self.VIDEO_WEIGHT +
            audio_score * self.AUDIO_WEIGHT
            # temporal_score * self.TEMPORAL_WEIGHT # Removed from overall calculation
        )
        
        # Determine grade
        grade = self._get_grade(overall_score)
        
        # Combine all issues
        video_issues = self.video_metrics.get("issues", [])
        audio_issues = self.audio_metrics.get("issues", [])
        all_issues = video_issues + audio_issues
        
        # Sort by severity
        severity_order = {"high": 0, "medium": 1, "low": 2}
        all_issues.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 2))
        
        return {
            "overall_score": round(overall_score, 1),
            "grade": grade,
            "video_score": round(video_score, 1),
            "audio_score": round(audio_score, 1),
            "temporal_score": round(temporal_score, 1),
            "breakdown": self._get_breakdown(video_score, audio_score, temporal_score),
            "issues": all_issues,
            "summary": self._generate_summary(overall_score, video_score, audio_score, temporal_score)
        }
    
    def _calculate_video_score(self) -> float:
        """Calculate video quality score (0-100)."""
        if self.video_metrics.get("error"):
            return 0
        
        # BRISQUE/quality score
        quality_score = self.video_metrics.get("brisque_score", 50)
        
        # Bitrate score
        bitrate = self.video_metrics.get("bitrate", 0)
        bitrate_score = self._normalize_bitrate(bitrate)
        
        # Resolution score
        resolution = self.video_metrics.get("resolution", {})
        width = resolution.get("width", 0)
        height = resolution.get("height", 0)
        resolution_score = self._normalize_resolution(width, height)
        
        # Weighted combination
        video_score = (
            quality_score * self.VIDEO_QUALITY_WEIGHT +
            bitrate_score * self.VIDEO_BITRATE_WEIGHT +
            resolution_score * self.VIDEO_RESOLUTION_WEIGHT
        )
        
        return max(0, min(100, video_score))
    
    def _calculate_audio_score(self) -> float:
        """Calculate audio quality score (0-100)."""
        if not self.audio_metrics.get("has_audio", False):
            # No audio track - neutral score (doesn't penalize video-only)
            return 75
        
        if self.audio_metrics.get("error"):
            return 50
        
        # SNR score
        snr_score = self.audio_metrics.get("snr_score", 50)
        
        # Speech clarity score
        clarity_score = self.audio_metrics.get("speech_clarity_score", 50)
        
        # Clipping score (higher = no clipping = good)
        clipping_score = self.audio_metrics.get("clipping_score", 100)
        
        # Weighted combination
        audio_score = (
            snr_score * self.AUDIO_SNR_WEIGHT +
            clarity_score * self.AUDIO_CLARITY_WEIGHT +
            clipping_score * self.AUDIO_CLIPPING_WEIGHT
        )
        
        # Additional penalties
        loudness = self.audio_metrics.get("loudness_lufs", -16)
        if loudness < -30:
            audio_score *= 0.9  # 10% penalty for too quiet
        elif loudness > -8:
            audio_score *= 0.9  # 10% penalty for too loud
        
        return max(0, min(100, audio_score))
    
    def _calculate_temporal_score(self) -> float:
        """Calculate temporal stability score (0-100)."""
        stability = self.video_metrics.get("temporal_stability", 100)
        consistency = self.video_metrics.get("frame_consistency", 100)
        
        # Quality drops penalty
        drops = self.video_metrics.get("quality_drops", [])
        drop_penalty = min(20, len(drops) * 4)
        
        # Combine stability and consistency
        temporal_score = (stability * 0.6 + consistency * 0.4) - drop_penalty
        
        return max(0, min(100, temporal_score))
    
    def _normalize_bitrate(self, bitrate_kbps: int) -> float:
        """Normalize bitrate to 0-100 score."""
        # Scoring based on typical good bitrates
        # < 1000 kbps = poor
        # 1000-2500 kbps = acceptable
        # 2500-5000 kbps = good
        # 5000-10000 kbps = very good
        # > 10000 kbps = excellent
        
        if bitrate_kbps >= 10000:
            return 100
        elif bitrate_kbps >= 5000:
            return 80 + (bitrate_kbps - 5000) / 250
        elif bitrate_kbps >= 2500:
            return 60 + (bitrate_kbps - 2500) / 125
        elif bitrate_kbps >= 1000:
            return 40 + (bitrate_kbps - 1000) / 75
        elif bitrate_kbps >= 500:
            return 20 + (bitrate_kbps - 500) / 25
        else:
            return max(0, bitrate_kbps / 25)
    
    def _normalize_resolution(self, width: int, height: int) -> float:
        """Normalize resolution to 0-100 score."""
        pixels = width * height
        
        # Resolution thresholds
        # 4K (3840x2160) = 8.3M pixels = 100
        # 1080p (1920x1080) = 2.1M pixels = 85
        # 720p (1280x720) = 0.92M pixels = 70
        # 480p (854x480) = 0.41M pixels = 50
        # 360p (640x360) = 0.23M pixels = 30
        
        if pixels >= 8000000:  # 4K+
            return 100
        elif pixels >= 2000000:  # 1080p+
            return 85 + (pixels - 2000000) / 400000
        elif pixels >= 900000:  # 720p+
            return 70 + (pixels - 900000) / 73333
        elif pixels >= 400000:  # 480p+
            return 50 + (pixels - 400000) / 25000
        elif pixels >= 200000:  # 360p+
            return 30 + (pixels - 200000) / 10000
        else:
            return max(0, pixels / 6667)
    
    def _get_grade(self, score: float) -> str:
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
    
    def _get_breakdown(self, video: float, audio: float, temporal: float) -> Dict[str, Any]:
        """Get detailed score breakdown."""
        return {
            "video": {
                "score": round(video, 1),
                "weight": f"{int(self.VIDEO_WEIGHT * 100)}%",
                "contribution": round(video * self.VIDEO_WEIGHT, 1),
                "components": {
                    "visual_quality": round(self.video_metrics.get("brisque_score", 50), 1),
                    "bitrate": self.video_metrics.get("bitrate", 0),
                    "resolution": f"{self.video_metrics.get('resolution', {}).get('width', 0)}x{self.video_metrics.get('resolution', {}).get('height', 0)}"
                }
            },
            "audio": {
                "score": round(audio, 1),
                "weight": f"{int(self.AUDIO_WEIGHT * 100)}%",
                "contribution": round(audio * self.AUDIO_WEIGHT, 1),
                "components": {
                    "snr_db": self.audio_metrics.get("snr_db", 0),
                    "clarity": round(self.audio_metrics.get("speech_clarity_score", 50), 1),
                    "loudness_lufs": self.audio_metrics.get("loudness_lufs", -16)
                }
            },
            "temporal": {
                "score": round(temporal, 1),
                "weight": f"{int(self.TEMPORAL_WEIGHT * 100)}%",
                "contribution": round(temporal * self.TEMPORAL_WEIGHT, 1),
                "components": {
                    "stability": round(self.video_metrics.get("temporal_stability", 100), 1),
                    "consistency": round(self.video_metrics.get("frame_consistency", 100), 1)
                }
            }
        }
    
    def _generate_summary(self, overall: float, video: float, audio: float, temporal: float) -> str:
        """Generate human-readable summary."""
        grade = self._get_grade(overall)
        
        # Overall assessment
        if overall >= 80:
            assessment = "Excellent quality"
        elif overall >= 65:
            assessment = "Good quality with minor issues"
        elif overall >= 50:
            assessment = "Acceptable quality with noticeable issues"
        else:
            assessment = "Poor quality with significant issues"
        
        # Identify weakest area
        scores = {"video": video, "audio": audio}
        weakest = min(scores, key=scores.get)
        strongest = max(scores, key=scores.get)
        
        summary = f"{assessment}. Grade: {grade}. "
        
        if scores[weakest] < 60:
            summary += f"Primary concern: {weakest} ({scores[weakest]:.0f}/100). "
        
        if scores[strongest] >= 80:
            summary += f"Strong performance in {strongest} ({scores[strongest]:.0f}/100)."
        
        return summary


def calculate_quality_score(video_metrics: Dict[str, Any], audio_metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to calculate quality score."""
    scorer = QualityScorer(video_metrics, audio_metrics)
    return scorer.calculate()
