"""
Transcript Analyzer Module for AI Media Quality Validator.
Uses faster-whisper for transcription and rapidfuzz for fuzzy brand name matching.
"""

import os
from typing import List, Dict, Any, Tuple
from faster_whisper import WhisperModel
from rapidfuzz import fuzz
import logging

logger = logging.getLogger("media_validator.transcript")

class TranscriptAnalyzer:
    """Analyzes audio transcripts for content compliance."""
    
    def __init__(self, model_size: str = "small", device: str = None):
        """
        Initialize the analyzer with Whisper model.
        Args:
            model_size: Size of the Whisper model (tiny, small, medium, large-v2).
            device: 'cuda' for GPU or 'cpu'. Auto-detected if None.
        """
        if device is None:
            device = "cpu" 
            
        self.model_size = model_size
        logger.info(f"Loading Whisper model: {model_size} on {device}...")
        try:
            self.model = WhisperModel(model_size, device=device, compute_type="int8")
            logger.info("Whisper model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            self.model = None

    def transcribe_audio(self, audio_path: str) -> List[Dict[str, Any]]:
        """
        Transcribe audio file to text segments in English.
        """
        if not self.model:
            logger.error("Model not initialized, cannot transcribe.")
            return []
            
        if not os.path.exists(audio_path):
            logger.error(f"Audio file not found: {audio_path}")
            return []

        logger.info(f"Starting transcription for: {audio_path} using model '{self.model_size}'...")
        try:
            segments, info = self.model.transcribe(
                audio_path, 
                beam_size=5,
                task="translate",
                language=None,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=200
                )
            )
            
            result_segments = []
            for segment in segments:
                words = []
                if hasattr(segment, 'words') and segment.words:
                    words = [{"word": w.word, "start": w.start, "end": w.end} for w in segment.words]
                
                result_segments.append({
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                    "words": words
                })
            
            logger.info(f"Transcription complete. Found {len(result_segments)} segments.")
            return result_segments
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return []

    def count_brand_mentions(self, segments: List[Dict[str, Any]], brand_name: str, threshold: int = 70) -> Dict[str, Any]:
        """
        Count mentions of a brand name in the transcript segments using fuzzy matching.
        """
        full_transcript = []
        for segment in segments:
            full_transcript.append({
                "time": round(segment["start"], 1),
                "text": segment["text"]
            })
        
        if not brand_name:
             return {
                "target_brand": None,
                "mention_count": 0,
                "timestamps": [],
                "transcript_snippet": "",
                "full_transcript": full_transcript
            }

        logger.info(f"Scanning for brand: '{brand_name}' with threshold {threshold}")
        
        mention_count = 0
        timestamps = []
        snippets = []
        
        normalized_brand = brand_name.lower()
        
        for segment in segments:
            text = segment["text"]
            words = text.split()
            segment_mentions = 0
            
            brand_parts = normalized_brand.split()
            brand_len = len(brand_parts)
            
            if brand_len == 1:
                # Single word brand - strict matching
                for word in words:
                    clean_word = "".join(c for c in word if c.isalnum()).lower()
                    if not clean_word:
                        continue
                    
                    if abs(len(clean_word) - len(normalized_brand)) > 2:
                        continue
                    
                    score = fuzz.ratio(normalized_brand, clean_word)
                    
                    # Higher threshold for short brand names
                    effective_threshold = 85 if len(normalized_brand) <= 5 else threshold
                    
                    if score >= effective_threshold:
                        segment_mentions += 1
                        logger.info(f"Brand match: '{clean_word}' score={score}")
            else:
                # Multi-word brand - Sliding window
                for i in range(len(words) - brand_len + 1):
                    window = words[i : i + brand_len]
                    window_text = " ".join(window)
                    clean_window = "".join(c for c in window_text if c.isalnum() or c.isspace()).lower()
                    
                    score = fuzz.ratio(normalized_brand, clean_window)
                    
                    if score >= threshold:
                        segment_mentions += 1
                        logger.info(f"Brand match: '{clean_window}' score={score}")
            
            if segment_mentions > 0:
                mention_count += segment_mentions
                timestamps.append(round(segment["start"], 2))
                snippets.append(f"[{round(segment['start'], 1)}s] {text}")

        display_snippet = " ... ".join(snippets[:5])
        if len(snippets) > 5:
            display_snippet += "..."

        return {
            "target_brand": brand_name,
            "mention_count": mention_count,
            "timestamps": timestamps,
            "transcript_snippet": display_snippet,
            "full_transcript": full_transcript
        }
