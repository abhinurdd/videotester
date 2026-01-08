import os
import sys

# Add current directory to path so we can import dependencies if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from faster_whisper import WhisperModel
    
    print("⬇️ Starting download of 'tiny' Whisper model...")
    
    # Initialize model - this triggers download
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    
    print("✅ Tiny Model downloaded and cached successfully!")
    
except Exception as e:
    print(f"❌ Error downloading model: {e}")
