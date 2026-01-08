"""
Audio Analysis Module for AI Media Quality Validator.
Analyzes audio quality using SNR, loudness (LUFS), clipping detection, and speech clarity.
"""

import numpy as np
import librosa
import soundfile as sf
import subprocess
import tempfile
import os
from typing import Dict, Any, List, Tuple
import json


class AudioAnalyzer:
    """Analyzes audio files/tracks for quality metrics."""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.audio_data = None
        self.sample_rate = None
        self.duration = 0
        
    def analyze(self) -> Dict[str, Any]:
        """Run complete audio analysis pipeline."""
        audio_path = self._extract_audio()
        
        if not audio_path:
            return {"error": "Could not extract audio", "has_audio": False}
        
        try:
            self.audio_data, self.sample_rate = librosa.load(audio_path, sr=None, mono=False)
            
            if len(self.audio_data.shape) == 1:
                self.audio_data = self.audio_data.reshape(1, -1)
            
            self.duration = len(self.audio_data[0]) / self.sample_rate
            
            metrics = {
                "has_audio": True,
                "sample_rate": self.sample_rate,
                "duration": round(self.duration, 2),
                "channels": self.audio_data.shape[0],
            }
            
            metrics.update(self._calculate_snr())
            metrics.update(self._calculate_loudness())
            metrics.update(self._detect_clipping())
            metrics.update(self._analyze_speech_clarity())
            metrics.update(self._analyze_frequency_content())
            
            issues = self._detect_issues(metrics)
            metrics["issues"] = issues
            
            if audio_path != self.filepath and os.path.exists(audio_path):
                os.remove(audio_path)
            
            return metrics
            
        except Exception as e:
            return {"error": str(e), "has_audio": False}
    
    def _extract_audio(self) -> str:
        """Extract audio track from video file."""
        audio_extensions = ['.wav', '.mp3', '.flac', '.aac', '.ogg', '.m4a']
        if any(self.filepath.lower().endswith(ext) for ext in audio_extensions):
            return self.filepath
        
        try:
            temp_audio = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            temp_path = temp_audio.name
            temp_audio.close()
            
            subprocess.run([
                'ffmpeg', '-y', '-i', self.filepath,
                '-vn', '-acodec', 'pcm_s16le',
                '-ar', '44100', '-ac', '2',
                temp_path
            ], capture_output=True, text=True)
            
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                return temp_path
            else:
                return None
                
        except Exception as e:
            print(f"Error extracting audio: {e}")
            return None
    
    def _calculate_snr(self) -> Dict[str, Any]:
        """Estimate Signal-to-Noise Ratio."""
        audio_mono = np.mean(self.audio_data, axis=0) if len(self.audio_data.shape) > 1 else self.audio_data[0]
        
        stft = librosa.stft(audio_mono)
        magnitude = np.abs(stft)
        
        frame_energy = np.sum(magnitude ** 2, axis=0)
        sorted_energy = np.sort(frame_energy)
        n_frames = len(sorted_energy)
        
        # Use bottom 10% of frames as noise estimate
        noise_frames = sorted_energy[:max(1, n_frames // 10)]
        noise_power = np.mean(noise_frames)
        
        # Use top 50% as signal estimate
        signal_frames = sorted_energy[n_frames // 2:]
        signal_power = np.mean(signal_frames)
        
        if noise_power > 0:
            snr = 10 * np.log10(signal_power / noise_power)
        else:
            snr = 60
        
        # Normalize SNR to 0-100 scale (0-10 dB = poor, 40+ dB = excellent)
        snr = max(0, min(60, snr))
        snr_score = min(100, snr * 2.5)
        
        return {
            "snr_db": round(snr, 2),
            "snr_score": round(snr_score, 2)
        }
    
    def _calculate_loudness(self) -> Dict[str, Any]:
        """Calculate loudness in LUFS and dynamic range."""
        audio_mono = np.mean(self.audio_data, axis=0) if len(self.audio_data.shape) > 1 else self.audio_data[0]
        
        try:
            import pyloudnorm as pyln
            meter = pyln.Meter(self.sample_rate)
            loudness = meter.integrated_loudness(audio_mono)
            if np.isinf(loudness) or np.isnan(loudness):
                loudness = -60
        except Exception:
            rms = np.sqrt(np.mean(audio_mono ** 2))
            if rms > 0:
                loudness = 20 * np.log10(rms) - 0.691
            else:
                loudness = -60
        
        # Calculate dynamic range using 400ms windows
        window_size = int(self.sample_rate * 0.4)
        hop_size = window_size // 2
        
        window_rms = []
        for i in range(0, len(audio_mono) - window_size, hop_size):
            window = audio_mono[i:i + window_size]
            rms = np.sqrt(np.mean(window ** 2))
            if rms > 0:
                window_rms.append(20 * np.log10(rms))
        
        if window_rms:
            dynamic_range = np.percentile(window_rms, 95) - np.percentile(window_rms, 5)
        else:
            dynamic_range = 0
        
        return {
            "loudness_lufs": round(loudness, 2),
            "dynamic_range_db": round(dynamic_range, 2),
            "peak_level_db": round(20 * np.log10(np.max(np.abs(audio_mono)) + 1e-10), 2)
        }
    
    def _detect_clipping(self) -> Dict[str, Any]:
        """Detect audio clipping (samples at max level)."""
        audio_mono = np.mean(self.audio_data, axis=0) if len(self.audio_data.shape) > 1 else self.audio_data[0]
        
        threshold = 0.99
        clipped_samples = np.sum(np.abs(audio_mono) >= threshold)
        total_samples = len(audio_mono)
        clip_ratio = clipped_samples / total_samples
        
        clipping_events = []
        is_clipped = np.abs(audio_mono) >= threshold
        
        diff = np.diff(is_clipped.astype(int))
        starts = np.where(diff == 1)[0] + 1
        ends = np.where(diff == -1)[0] + 1
        
        if is_clipped[0]:
            starts = np.concatenate([[0], starts])
        if is_clipped[-1]:
            ends = np.concatenate([ends, [len(is_clipped)]])
        
        for start, end in zip(starts[:10], ends[:10]):
            duration_samples = end - start
            if duration_samples > self.sample_rate * 0.001:
                timestamp = start / self.sample_rate
                clipping_events.append({
                    "timestamp": round(timestamp, 2),
                    "duration_ms": round(duration_samples / self.sample_rate * 1000, 1)
                })
        
        return {
            "clipping_ratio": round(clip_ratio * 100, 4),
            "has_clipping": clip_ratio > 0.0001,
            "clipping_events": clipping_events,
            "clipping_score": round(max(0, 100 - clip_ratio * 10000), 2)
        }
    
    def _analyze_speech_clarity(self) -> Dict[str, Any]:
        """Analyze speech clarity using spectral features."""
        audio_mono = np.mean(self.audio_data, axis=0) if len(self.audio_data.shape) > 1 else self.audio_data[0]
        
        stft = librosa.stft(audio_mono)
        magnitude = np.abs(stft)
        freqs = librosa.fft_frequencies(sr=self.sample_rate)
        
        speech_low = np.argmin(np.abs(freqs - 85))
        speech_high = np.argmin(np.abs(freqs - 8000))
        
        speech_energy = np.sum(magnitude[speech_low:speech_high, :] ** 2)
        total_energy = np.sum(magnitude ** 2)
        
        speech_ratio = speech_energy / total_energy if total_energy > 0 else 0
        
        formant_low = np.argmin(np.abs(freqs - 300))
        formant_high = np.argmin(np.abs(freqs - 3000))
        formant_energy = np.sum(magnitude[formant_low:formant_high, :] ** 2)
        
        spectral_centroid = librosa.feature.spectral_centroid(y=audio_mono, sr=self.sample_rate)
        avg_centroid = np.mean(spectral_centroid)
        
        clarity_score = min(100, speech_ratio * 100 + (formant_energy / max(1, total_energy)) * 50)
        
        return {
            "speech_energy_ratio": round(speech_ratio * 100, 2),
            "spectral_centroid_hz": round(avg_centroid, 0),
            "speech_clarity_score": round(clarity_score, 2)
        }
    
    def _analyze_frequency_content(self) -> Dict[str, Any]:
        """Analyze frequency content distribution."""
        audio_mono = np.mean(self.audio_data, axis=0) if len(self.audio_data.shape) > 1 else self.audio_data[0]
        
        stft = librosa.stft(audio_mono)
        magnitude = np.abs(stft)
        freqs = librosa.fft_frequencies(sr=self.sample_rate)
        
        avg_spectrum = np.mean(magnitude, axis=1)
        
        bass_range = (20, 250)
        mid_range = (250, 4000)
        high_range = (4000, min(20000, self.sample_rate // 2))
        
        def band_energy(low, high):
            low_bin = np.argmin(np.abs(freqs - low))
            high_bin = np.argmin(np.abs(freqs - high))
            return np.sum(avg_spectrum[low_bin:high_bin] ** 2)
        
        bass = band_energy(*bass_range)
        mid = band_energy(*mid_range)
        high = band_energy(*high_range)
        total = bass + mid + high
        
        if total > 0:
            return {
                "bass_ratio": round(bass / total * 100, 1),
                "mid_ratio": round(mid / total * 100, 1),
                "high_ratio": round(high / total * 100, 1),
                "frequency_balance": "balanced" if 15 < bass/total*100 < 40 and 40 < mid/total*100 < 70 else "unbalanced"
            }
        
        return {
            "bass_ratio": 0,
            "mid_ratio": 0,
            "high_ratio": 0,
            "frequency_balance": "unknown"
        }
    
    def _detect_issues(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect audio quality issues based on metrics."""
        issues = []
        
        if metrics.get("has_clipping"):
            events = metrics.get("clipping_events", [])
            if events:
                timestamps = ", ".join([f"{e['timestamp']}s" for e in events[:3]])
                issues.append({
                    "type": "audio",
                    "severity": "high",
                    "message": f"Audio clipping detected at: {timestamps}",
                    "recommendation": "Reduce input gain or normalize audio to prevent distortion"
                })
        
        snr = metrics.get("snr_db", 0)
        if snr < 10:
            issues.append({
                "type": "audio",
                "severity": "high",
                "message": f"Very low SNR: {snr:.1f} dB",
                "recommendation": "Audio has significant background noise, consider noise reduction"
            })
        elif snr < 20:
            issues.append({
                "type": "audio",
                "severity": "medium",
                "message": f"Low SNR: {snr:.1f} dB",
                "recommendation": "Noticeable background noise present"
            })
        
        loudness = metrics.get("loudness_lufs", -24)
        if loudness < -30:
            issues.append({
                "type": "audio",
                "severity": "medium",
                "message": f"Audio too quiet: {loudness:.1f} LUFS",
                "recommendation": "Consider normalizing audio to -14 to -16 LUFS"
            })
        elif loudness > -10:
            issues.append({
                "type": "audio",
                "severity": "medium",
                "message": f"Audio very loud: {loudness:.1f} LUFS",
                "recommendation": "Audio may cause discomfort, consider reducing levels"
            })
        
        dynamic_range = metrics.get("dynamic_range_db", 0)
        if dynamic_range < 6:
            issues.append({
                "type": "audio",
                "severity": "low",
                "message": f"Low dynamic range: {dynamic_range:.1f} dB",
                "recommendation": "Audio may sound compressed or fatiguing"
            })
        
        clarity = metrics.get("speech_clarity_score", 50)
        if clarity < 30:
            issues.append({
                "type": "audio",
                "severity": "medium",
                "message": "Low speech clarity score",
                "recommendation": "Speech may be difficult to understand"
            })
        
        sample_rate = metrics.get("sample_rate", 44100)
        if sample_rate < 22050:
            issues.append({
                "type": "audio",
                "severity": "high",
                "message": f"Low sample rate: {sample_rate} Hz",
                "recommendation": "Audio quality limited by low sample rate"
            })
        
        return issues
