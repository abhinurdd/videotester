import os
import sys

# Add current directory to path so we can import dependencies if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from faster_whisper import WhisperModel
    
    print("⬇️ Starting download of 'small' Whisper model...")
    print("This may take a few minutes depending on internet speed.")
    
    # Initialize model - this triggers download
    model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    
    print("✅ Model downloaded and cached successfully!")
    print("You can now run the analysis without waiting.")
    
except ImportError:
    print("❌ faster-whisper not installed. Please install requirements first.")
except Exception as e:
    print(f"❌ Error downloading model: {e}")
