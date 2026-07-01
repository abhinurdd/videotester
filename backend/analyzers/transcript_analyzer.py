"""
Transcript Analyzer Module for AI Media Quality Validator.
Uses Groq API for transcription and rapidfuzz for fuzzy brand name matching.
"""

import os
import sys
from typing import List, Dict, Any, Tuple
from groq import Groq
from rapidfuzz import fuzz
import logging
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("media_validator.transcript")

class TranscriptAnalyzer:
    """Analyzes audio transcripts for content compliance using Groq API."""
    
    def __init__(self, model_size: str = "whisper-large-v3", device: str = None):
        self.model_size = model_size
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        if not self.groq_api_key:
            logger.error("GROQ_API_KEY not found in environment variables")
            self.client = None
        else:
            self.client = Groq(api_key=self.groq_api_key)
            
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openai_client = OpenAI(api_key=self.openai_api_key) if self.openai_api_key else None
        
        logger.info(f"TranscriptAnalyzer initialized using Groq API ({model_size})")

    def transcribe_audio(self, audio_path: str, brand_hint: str = None) -> List[Dict[str, Any]]:
        if not self.client:
            logger.error("Groq client not initialized")
            return []

        logger.info(f"Transcribing audio via Groq: {audio_path}")
        
        temp_path = None
        try:
            import tempfile
            import subprocess
            
            # Create a temp WAV file for Groq (16kHz, Mono) to ensure high quality and small size
            temp_audio = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            temp_path = temp_audio.name
            temp_audio.close()
            
            logger.info(f"Extracting/Converting audio to 16kHz Mono WAV for Groq: {temp_path}")
            
            # Use FFmpeg to convert to 16kHz, Mono WAV
            result = subprocess.run([
                'ffmpeg', '-y', '-i', audio_path,
                '-vn',                  # No video
                '-acodec', 'pcm_s16le', # 16-bit PCM
                '-ar', '16000',         # 16kHz (native for Whisper)
                '-ac', '1',             # Mono
                temp_path
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg failed: {result.stderr}")
                raise Exception(f"FFmpeg extraction failed: {result.stderr}")

            with open(temp_path, "rb") as file:
                filename = os.path.basename(temp_path)
                transcription = self.client.audio.transcriptions.create(
                    file=(filename, file.read()),
                    model=self.model_size,
                    temperature=0.03,
                    response_format="verbose_json",
                )
            
            # Convert Groq response to the format expected by the rest of the app
            result_segments = []
            
            # TranscriptionVerbose from Groq can be an object or a dict depending on the SDK version
            segments = getattr(transcription, 'segments', [])
            if not segments and isinstance(transcription, dict):
                segments = transcription.get('segments', [])
                
            if segments:
                for segment in segments:
                    # Robust attribute/key access
                    if isinstance(segment, dict):
                        start = segment.get('start', 0)
                        end = segment.get('end', 0)
                        text = segment.get('text', '').strip()
                    else:
                        start = getattr(segment, 'start', 0)
                        end = getattr(segment, 'end', 0)
                        text = getattr(segment, 'text', '').strip()
                    
                    result_segments.append({
                        "start": float(start),
                        "end": float(end),
                        "text": text,
                        "language": getattr(transcription, 'language', 'unknown') if not isinstance(transcription, dict) else transcription.get('language', 'unknown')
                    })
            elif hasattr(transcription, 'text') or (isinstance(transcription, dict) and 'text' in transcription):
                # Fallback if segments are not available but text is
                text = getattr(transcription, 'text', '').strip() if not isinstance(transcription, dict) else transcription.get('text', '').strip()
                result_segments.append({
                    "start": 0.0,
                    "end": 0.0,
                    "text": text,
                    "language": getattr(transcription, 'language', 'unknown') if not isinstance(transcription, dict) else transcription.get('language', 'unknown')
                })
            
            logger.info(f"Groq transcription complete. Found {len(result_segments)} segments.")
            return result_segments
        except Exception as e:
            logger.error(f"Groq transcription failed: {e}")
            return []
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                    logger.info(f"Cleaned up temp audio file: {temp_path}")
                except Exception as e:
                    logger.error(f"Failed to delete temp file {temp_path}: {e}")

    def count_brand_mentions(self, segments: List[Dict[str, Any]], brand_name: str, threshold: int = 60) -> Dict[str, Any]:
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
                
                # More robust merging of GPT data with original segments
                gpt_transcript = gpt_data.get("transcript", [])
                final_transcript = []
                
                # Match GPT segments back to original segments to ensure no data loss
                for i, orig in enumerate(full_transcript):
                    merged = {
                        "time": orig["time"],
                        "hinglish": orig["text"], # Default to original transcription
                        "english": ""
                    }
                    
                    if i < len(gpt_transcript):
                        g = gpt_transcript[i]
                        h = g.get("hinglish", "").strip()
                        e = g.get("english", "").strip()
                        
                        # Only use GPT data if it looks valid and isn't a placeholder
                        if h and h not in ["", "[--]", "...", "---", "[missing]"]:
                            merged["hinglish"] = h
                        if e and e not in ["", "[--]", "...", "---", "[missing]"]:
                            merged["english"] = e
                    
                    final_transcript.append(merged)

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
            "You are an expert in Indian Pop Culture and Verbatim Transcript Restoration. "
            "You are correcting a rough Whisper transcription of a Hinglish (Hindi/Marathi/English mix) conversation. "
            f"The target brand is: '{brand_name}'.\n\n"
            "CONTEXTUAL KNOWLEDGE:\n"
            f"- TARGET BRAND: '{brand_name}'. If the transcription says 'vote', 'voted', 'bhote', or 'wote' in an electronics/audio context, ALWAYS correct it to '{brand_name}'.\n"
            "- POP CULTURE: 'Samay' (Samay Raina), 'Krishna/Krsna' (the rapper), 'diss track' (not distract/distracts), 'raps' (not wraps).\n"
            "- PHONETIC FIXES: 'kabhi' (not kami), 'bahas' (not bais), 'kaun' (not kaur), 'taarikh' (not taari), 'bhai' (not bai), 'arre' (not are).\n\n"
            "STRICT RULES:\n"
            "1. NO MERGING: Return exactly the same number of segments. Preserve timestamps.\n"
            "2. PHONETIC CORRECTION: Fix common Whisper errors in the 'hinglish' field. "
            "If Whisper says 'kami bais', but the context is 'argue', fix it to 'kabhi bahas'.\n"
            "3. SCRIPT ENFORCEMENT: Use ONLY Roman Script (English letters). Example: 'नमस्ते' -> 'namaste'.\n"
            "4. HINGLISH FIELD: Verbatim spoken words in Roman script, but corrected for phonetic errors. No translation here.\n"
            "5. ENGLISH FIELD: High-quality, natural English translation.\n"
            "6. BRAND DETECTION: Identify every timestamp where the brand is mentioned, even if misspelled in the source.\n\n"
            "Respond ONLY as JSON:\n"
            "{\n"
            "  \"mention_count\": number,\n"
            "  \"timestamps\": [45.0, 48.2],\n"
            "  \"transcript\": [\n"
            "    {\"time\": 0.0, \"hinglish\": \"text\", \"english\": \"translation\"}\n"
            "  ]\n"
            "}"
        )

        try:
            logger.info(f"Sending {len(segments)} segments to GPT for restoration...")
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": prompt}, 
                    {"role": "user", "content": f"Restore this transcript for brand '{brand_name}':\n\n{input_text}"}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            import json
            content = response.choices[0].message.content
            logger.debug(f"GPT Response: {content}")
            return json.loads(content)
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return {}
