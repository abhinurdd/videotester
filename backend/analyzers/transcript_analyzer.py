"""
Transcript Analyzer Module for AI Media Quality Validator.
Uses faster-whisper for transcription and rapidfuzz for fuzzy brand name matching.
"""

import os
import sys
from typing import List, Dict, Any, Tuple
from faster_whisper import WhisperModel
from rapidfuzz import fuzz
import logging
from openai import OpenAI
from dotenv import load_dotenv

# --- Windows CUDA DLL Fix Start ---
if os.name == 'nt':
    import site
    packages = site.getsitepackages()
    for package in packages:
        nvidia_path = os.path.join(package, 'nvidia')
        if os.path.exists(nvidia_path):
            subdirs = ['cublas', 'cudnn']
            for subdir in subdirs:
                bin_path = os.path.join(nvidia_path, subdir, 'bin')
                if os.path.exists(bin_path):
                    os.environ['PATH'] = bin_path + os.pathsep + os.environ['PATH']
                    if hasattr(os, 'add_dll_directory'):
                        os.add_dll_directory(bin_path)
# --- Windows CUDA DLL Fix End ---

load_dotenv()

logger = logging.getLogger("media_validator.transcript")

class TranscriptAnalyzer:
    """Analyzes audio transcripts for content compliance."""
    
    def __init__(self, model_size: str = "large-v3", device: str = None):
        if device is None:
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
            
        self.model_size = model_size
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openai_client = OpenAI(api_key=self.openai_api_key) if self.openai_api_key else None
        
        compute_type = "float16" if device == "cuda" else "float32"
        logger.info(f"Loading Whisper model: {model_size} (Device: {device}, Precision: {compute_type})...")
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            if device == "cuda":
                try:
                    self.model = WhisperModel(model_size, device="cpu", compute_type="float32")
                except Exception:
                    self.model = None

    def transcribe_audio(self, audio_path: str, brand_hint: str = None) -> List[Dict[str, Any]]:
        if not self.model: return []

        prompt = (
            "This is a multilingual video (English, Hindi, Marathi, etc.). "
            "Please transcribe exactly what is spoken. "
            "For Indic languages like Hindi or Marathi, use Romanized script (English letters). "
            "Do not translate to English here."
        )
        if brand_hint:
            prompt += f" Brand mention: {brand_hint}."
        
        try:
            segments, info = self.model.transcribe(
                audio_path, 
                beam_size=5,
                language=None,
                initial_prompt=prompt,
                word_timestamps=True
            )
            
            result_segments = []
            for segment in segments:
                result_segments.append({
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                    "language": info.language
                })
            
            logger.info(f"Transcription complete. Found {len(result_segments)} segments in {info.language}.")
            return result_segments
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return []

    def count_brand_mentions(self, segments: List[Dict[str, Any]], brand_name: str, threshold: int = 70) -> Dict[str, Any]:
        full_transcript = []
        for segment in segments:
            full_transcript.append({
                "time": round(segment["start"], 1),
                "text": segment["text"]
            })
        
        if not brand_name:
             return {"target_brand": None, "mention_count": 0, "timestamps": [], "full_transcript": full_transcript}

        logger.info(f"Scanning for brand: '{brand_name}'")
        
        raw_mention_count = 0
        raw_timestamps = []
        
        normalized_brand = brand_name.lower()
        for segment in segments:
            text = segment["text"].lower()
            if normalized_brand in text or fuzz.partial_ratio(normalized_brand, text) >= threshold:
                raw_mention_count += 1
                raw_timestamps.append(round(segment["start"], 1))

        if self.openai_client:
            try:
                gpt_data = self.analyze_with_gpt(full_transcript, brand_name)
                
                final_transcript = gpt_data.get("transcript", full_transcript)
                final_mention_count = gpt_data.get("mention_count", raw_mention_count)
                
                gpt_timestamps = gpt_data.get("timestamps", [])
                final_timestamps = [float(t) for t in gpt_timestamps if isinstance(t, (int, float, str)) and str(t).replace('.','',1).isdigit()]
                
                if not final_timestamps and raw_mention_count > 0:
                    final_timestamps = raw_timestamps
                
                return {
                    "target_brand": brand_name,
                    "mention_count": final_mention_count,
                    "timestamps": final_timestamps,
                    "full_transcript": final_transcript
                }
            except Exception as e:
                logger.error(f"GPT analysis failed: {e}")
        
        return {
            "target_brand": brand_name,
            "mention_count": raw_mention_count,
            "timestamps": raw_timestamps,
            "full_transcript": full_transcript
        }

    def analyze_with_gpt(self, segments: List[Dict[str, Any]], brand_name: str) -> Dict[str, Any]:
        if not segments: return {}

        input_text = "\n".join([f"[{s['time']}s] {s['text']}" for s in segments])
        
        prompt = (
            "You are a verbatim transcript restoration expert. "
            f"Brand name: '{brand_name}'."
            "\n\nSTRICT RULES:\n"
            "1. NO MERGING: You must return the same number of segments as provided. Each input timestamp MUST have a corresponding output.\n"
            "2. SCRIPT ENFORCEMENT: For ALL non-Roman languages (Hindi, Marathi, Telugu, Tamil, Kannada, Arabic, etc.), transliterate the words into the ROMAN SCRIPT (English letters). "
            "Example: 'नमस्ते' becomes 'namaste'. DO NOT use original scripts like Devanagari or Telugu script.\n"
            "3. NO TRANSLATION IN HINGLISH/ORIGINAL FIELD: In the 'hinglish' field, provide the original spoken words (transliterated if non-Roman). "
            "For example, if the user speaks Marathi, write the Marathi words in English letters. DO NOT TRANSLATE TO ENGLISH IN THIS FIELD.\n"
            "4. ENGLISH FIELD: Provide a natural English translation here.\n"
            "5. BRAND DETECTION: Identify every exact timestamp where the brand was mentioned.\n\n"
            "Respond ONLY as JSON:\n"
            "{\n"
            "  \"mention_count\": number,\n"
            "  \"timestamps\": [list of times like 45.0, 48.2],\n"
            "  \"transcript\": [\n"
            "    {\"time\": 0.0, \"hinglish\": \"original words\", \"english\": \"translation\"}\n"
            "  ]\n"
            "}"
        )

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": input_text}],
                temperature=0,
                response_format={"type": "json_object"}
            )
            import json
            return json.loads(response.choices[0].message.content)
        except Exception:
            return {}
