# System Architecture & Technical Specifications

This document details the internal design, asynchronous pipeline, mathematical scoring algorithms, database schemas, and infrastructure optimizations of the AI Media Quality Validator.

---

## 1. Architectural Overview

The application follows an asynchronous event-driven architecture designed to process high-resolution video, audio, and images without blocking the HTTP request-response cycle.

```
                           +---------------------------+
                           |  Client (Web / External)  |
                           +-------------+-------------+
                                         |
                                         v
                         +-------------------------------+
                         |   FastAPI Gateway (Port 6969)  |
                         | - Ingestion (Upload / R2 URL) |
                         | - Status Polling & Results    |
                         +-------+---------------+-------+
                                 |               |
                    Task Enqueue |               | Query Status
                                 v               v
                         +---------------+---------------+
                         |   Redis Broker & Cache        |
                         |   (Port 6379, 128MB LRU)      |
                         +---------------+---------------+
                                         |
                                 Consume |
                                         v
                         +-------------------------------+
                         |     Celery Worker Process     |
                         |  (Concurrency 1, max-tasks 10)|
                         +---------------+---------------+
                                         |
         +-------------------------------+-------------------------------+
         |                               |                               |
         v                               v                               v
+------------------+           +-------------------+           +-------------------+
|  Video Analyzer  |           |   Audio Analyzer  |           | Transcript Worker |
| - FFmpeg/Probe   |           | - FFmpeg Extract  |           | - ThreadPool      |
| - OpenCV Frame   |           | - Librosa SNR     |           | - Groq Whisper    |
| - BRISQUE / Sobel|           | - LUFS / Clipping |           | - GPT-4o Entity   |
+--------+---------+           +---------+---------+           +---------+---------+
         |                               |                               |
         +-------------------------------+-------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |   Scoring Engine & SQLite DB  |
                         |  (aiosqlite media_validator)  |
                         +---------------+---------------+
                                         |
                                         v
                         +-------------------------------+
                         | Webhook Dispatch (Callback)   |
                         | (X-Callback-Secret / WAF pass)|
                         +-------------------------------+
```

---

## 2. Core Modules & Analyzers

### 2.1 Video Analyzer (`backend/analyzers/video_analyzer.py`)
Processes video streams using `ffprobe` and `OpenCV`:
- **Probe Inspection**: Extracts native container duration, codec, bitrate, width, height, and FPS.
- **Sampled Frame Analysis**: Samples 1 frame per second (capped at 60 frames max to limit memory and CPU load).
- **Perceptual Sharpness / Quality**:
  - Primary: OpenCV BRISQUE model (`QualityBRISQUE`).
  - Fallback: Grayscale Laplacian variance with noise penalty subtraction:
    $$\text{Sharpness} = \text{Var}(\nabla^2 I) - \min(20, \text{NoiseLevel} \times 2)$$
- **Artifact Detection**:
  - Evaluates average brightness; flags dark frames ($<30$).
  - Detects blocking artifacts in dark frames by measuring the ratio of 8x8 block boundary Sobel gradients to overall scene gradients.
- **Temporal Stability**:
  - Calculates frame-to-frame score variance and standard deviation.
  - Detects localized quality drops where a frame score dips 2 standard deviations below the mean.

### 2.2 Audio Analyzer (`backend/analyzers/audio_analyzer.py`)
Processes audio tracks extracted via FFmpeg to 16-bit 44.1kHz stereo PCM WAV:
- **Signal-to-Noise Ratio (SNR)**:
  - Computes Short-Time Fourier Transform (STFT) magnitude spectrogram.
  - Estimates noise power from the bottom 10% energy frames and signal power from the top 50% energy frames:
    $$\text{SNR}_{\text{dB}} = 10 \log_{10}\left(\frac{P_{\text{signal}}}{P_{\text{noise}}}\right)$$
- **Loudness & Dynamic Range**:
  - Measures integrated loudness in **LUFS** using ITU-R BS.1770 standards (via `pyloudnorm` or RMS fallback).
  - Evaluates dynamic range across 400ms sliding windows (95th percentile minus 5th percentile).
- **Clipping Detection**:
  - Scans sample amplitudes; detects consecutive samples peaking at $\ge 0.99$.
  - Flags clipping events longer than 1ms and computes total clip ratio.
- **Speech Clarity & Formant Energy**:
  - Computes spectral centroid (center of mass of frequency spectrum).
  - Calculates speech energy ratio ($85\text{ Hz} - 8000\text{ Hz}$) and vowel formant energy ratio ($300\text{ Hz} - 3000\text{ Hz}$).
- **Three-Band Frequency Balance**:
  - Categorizes spectrum into Bass ($20-250\text{ Hz}$), Mid ($250-4000\text{ Hz}$), and High ($4000-20000\text{ Hz}$).

### 2.3 Image Analyzer (`backend/analyzers/image_analyzer.py`)
Dedicated evaluator for static image posts:
- **PIL Technical Metrics**:
  - Image dimensions, aspect ratio, and landscape/portrait classification.
  - Grayscale mean brightness.
  - Standard deviation sharpness score.
- **GPT-4o Vision Content & Aesthetic Audit**:
  - Classifies visual content type (e.g., product photo, lifestyle, graphic).
  - Performs full OCR text extraction.
  - Detects brand logos, visibility (`none`, `low`, `medium`, `high`), obstruction, and prominence.
  - Rates composition and vibrancy on a 0-100 scale.
- **Composite Image Scoring**:
  $$\text{Overall Score} = 0.40 \times \text{Technical} + 0.30 \times \text{Aesthetic} + 0.30 \times \text{Brand}$$

### 2.4 Speech Transcription & Brand Compliance (`backend/analyzers/transcript_analyzer.py`)
- **Parallel Audio Pipeline**:
  - When a `brand_name` is supplied, the worker spawns a separate background thread via `ThreadPoolExecutor` to execute transcription concurrently while OpenCV and Librosa execute on the main worker thread.
  - Extracts 16kHz mono WAV (optimized specifically for Whisper models).
  - Transcribes via Groq Cloud API using `whisper-large-v3` with low temperature (`0.03`) for speed and fidelity.
- **LLM Transcript Restoration**:
  - Sends raw Whisper segments to OpenAI GPT-4o with an Indian pop-culture and Hinglish phonetic restoration prompt.
  - Corrects phonetic mistranscriptions (e.g. "vote" $\rightarrow$ "boAt", "kami bais" $\rightarrow$ "kabhi bahas").
  - Produces dual outputs: phonetic Hinglish in Roman script and natural English translation.
- **Brand Mention Tracking**:
  - Scans transcript segments with fuzzy string matching (`rapidfuzz.fuzz.partial_ratio` with $\ge 60$ threshold) combined with GPT-4o entity verification.
  - Emits exact timestamps where the brand is mentioned.

---

## 3. Detailed Scoring Formulas

```
+-----------------------------------------------------------------+
|                       OVERALL MEDIA SCORE                       |
|           50% Video Score      +      50% Audio Score           |
+--------------------------------+--------------------------------+
               |                                 |
               v                                 v
+-------------------------------+ +-------------------------------+
|          VIDEO SCORE          | |          AUDIO SCORE          |
| 50% Visual Quality (BRISQUE)  | | 30% Signal-to-Noise Ratio     |
| 30% Normalized Bitrate        | | 40% Speech Clarity            |
| 20% Resolution Target Score   | | 30% Clipping Resistance       |
+-------------------------------+ +-------------------------------+
```

### Video Quality Calculations
1. **Resolution Score ($0-100$)**:
   $$\text{Pixels} = \text{Width} \times \text{Height}$$
   - $\ge 8{,}000{,}000$ (4K): $100$
   - $\ge 2{,}000{,}000$ (1080p): $85 + \frac{\text{Pixels} - 2{,}000{,}000}{400{,}000}$
   - $\ge 900{,}000$ (720p): $70 + \frac{\text{Pixels} - 900{,}000}{73{,}333}$
   - $\ge 400{,}000$ (480p): $50 + \frac{\text{Pixels} - 400{,}000}{25{,}000}$
   - $\ge 200{,}000$ (360p): $30 + \frac{\text{Pixels} - 200{,}000}{10{,}000}$
   - $< 200{,}000$: $\frac{\text{Pixels}}{6{,}667}$
2. **Bitrate Score ($0-100$)**:
   - $\ge 10{,}000\text{ kbps}$: $100$
   - $\ge 5{,}000\text{ kbps}$: $80 + \frac{\text{Bitrate} - 5{,}000}{250}$
   - $\ge 2{,}500\text{ kbps}$: $60 + \frac{\text{Bitrate} - 2{,}500}{125}$
   - $\ge 1{,}000\text{ kbps}$: $40 + \frac{\text{Bitrate} - 1{,}000}{75}$
   - $< 1{,}000\text{ kbps}$: $\frac{\text{Bitrate}}{25}$

### Grade Thresholds
$$\text{Grade} = \begin{cases}
\text{A+} & \text{Score} \ge 90 \\
\text{A} & 85 \le \text{Score} < 90 \\
\text{A-} & 80 \le \text{Score} < 85 \\
\text{B+} & 75 \le \text{Score} < 80 \\
\text{B} & 70 \le \text{Score} < 75 \\
\text{B-} & 65 \le \text{Score} < 70 \\
\text{C+} & 60 \le \text{Score} < 65 \\
\text{C} & 55 \le \text{Score} < 60 \\
\text{C-} & 50 \le \text{Score} < 55 \\
\text{D+} & 45 \le \text{Score} < 50 \\
\text{D} & 40 \le \text{Score} < 45 \\
\text{F} & \text{Score} < 40
\end{cases}$$

---

## 4. Database Schema & Storage

The application uses **SQLite** through `aiosqlite` for asynchronous disk persistence.

### `files` Table
Stores uploaded or downloaded media metadata.
```sql
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    duration REAL,
    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `analyses` Table
Stores calculated evaluation metrics, raw analyzer JSON outputs, and detected quality issues.
```sql
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    overall_score REAL NOT NULL,
    video_score REAL,
    audio_score REAL,
    temporal_score REAL,
    raw_metrics TEXT,
    issues TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);
```

### Redis Key Patterns
- **Key**: `status:{file_id}`
- **Type**: String (JSON encoded)
- **TTL**: `3600` seconds (1 hour)
- **Structure**:
  ```json
  {
    "status": "processing",
    "progress": 50,
    "message": "Analyzing audio..."
  }
  ```

---

## 5. Concurrency, Queue & Resource Management

Media processing involves high memory and CPU utilization. The following production controls are enforced:

1. **Celery Worker Configuration**:
   - Concurrency set to `1` on production (`--concurrency=1`): Ensures that single video encoding / decoding loops utilize available compute without thrashing CPU caches or starving the OS.
   - Max tasks per child (`--max-tasks-per-child=10`): Celery worker processes are automatically terminated and re-spawned after 10 tasks to prevent memory leaks from OpenCV and Librosa C-extensions.
2. **Explicit Garbage Collection**:
   - `gc.collect()` is explicitly invoked after the video frame analysis pass and after the audio Librosa pass in `worker.py`.
3. **Redis Connection Pooling**:
   - Both API and Worker configure `redis.ConnectionPool` with `max_connections=10` (API) and `max_connections=5` (Worker).
   - `health_check_interval=30` and `socket_keepalive=True` prevent broken pipes when connected to cloud-hosted Redis providers (e.g. RedisLabs / Upstash).
   - Retry strategy: `ExponentialBackoff(3)` with `retry_on_timeout=True`.
4. **Temporary File Cleanup**:
   - Uploaded files or R2 downloaded artifacts are guaranteed to be unlinked in `finally` blocks within `worker.py`.
