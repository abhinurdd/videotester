# Local Setup & Development Guide

Comprehensive step-by-step guide for setting up and running the AI Media Quality Validator on your local machine (Windows, macOS, or Linux).

---

## Table of Contents
1. [Prerequisites](#1-prerequisites)
   - [FFmpeg Installation (Critical)](#ffmpeg-installation-critical)
   - [Python Environment](#python-environment)
   - [Redis Server](#redis-server)
2. [Method A: Docker Compose (Fastest & Recommended)](#2-method-a-docker-compose-fastest--recommended)
3. [Method B: Native Local Setup (Step-by-Step)](#3-method-b-native-local-setup-step-by-step)
   - [Step 1: Clone Repository & Virtual Environment](#step-1-clone-repository--virtual-environment)
   - [Step 2: Install Python Dependencies](#step-2-install-python-dependencies)
   - [Step 3: Configure Environment Variables (.env)](#step-3-configure-environment-variables-env)
   - [Step 4: Start Redis Broker](#step-4-start-redis-broker)
   - [Step 5: Start Celery Worker (Windows vs Linux)](#step-5-start-celery-worker)
   - [Step 6: Start FastAPI Server](#step-6-start-fastapi-server)
4. [Verifying Your Installation](#4-verifying-your-installation)
5. [Common Issues & Troubleshooting](#5-common-issues--troubleshooting)

---

## 1. Prerequisites

### FFmpeg Installation (Critical)
The video analyzer, audio extractor, and Groq pre-processor require `ffmpeg` and `ffprobe` in your system `PATH`.

- **Windows**:
  1. Download the release build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or via winget:
     ```powershell
     winget install Gyan.FFmpeg
     ```
  2. Verify in a fresh terminal:
     ```powershell
     ffmpeg -version
     ffprobe -version
     ```
- **macOS** (Homebrew):
  ```bash
  brew install ffmpeg
  ```
- **Linux** (Ubuntu/Debian):
  ```bash
  sudo apt update && sudo apt install -y ffmpeg
  ```

---

### Python Environment
- Python 3.10, 3.11, or 3.12 (Tested through Python 3.13).

---

### Redis Server
Redis is required for task queueing and status polling.
- **Option 1 (Docker - easiest)**:
  ```bash
  docker run -d --name local-redis -p 6379:6379 redis:7-alpine
  ```
- **Option 2 (Windows WSL2 or native port)**:
  ```bash
  wsl redis-server
  ```
- **Option 3 (macOS Homebrew)**:
  ```bash
  brew services start redis
  ```
- **Option 4 (Linux)**:
  ```bash
  sudo systemctl start redis-server
  ```

---

## 2. Method A: Docker Compose (Fastest & Recommended)

Docker runs Redis, API, and the Celery worker in isolated containers with FFmpeg pre-installed. No manual dependencies required.

### 1. Ensure Docker Desktop is running
Verify:
```bash
docker --version
```

### 2. Configure Environment
Create `.env` inside `backend/.env` (or project root):
```env
GROQ_API_KEY=gsk_your_groq_key_here
OPENAI_API_KEY=sk-proj-your_openai_key_here
```

### 3. Launch Development Stack
```bash
# Starts Redis, API (with hot-reload), and Celery worker
docker compose -f docker-compose.dev.yml up -d --build
```

### 4. Monitor Logs
```bash
# View all logs
docker compose -f docker-compose.dev.yml logs -f

# View worker logs only
docker compose -f docker-compose.dev.yml logs -f worker
```

Open `http://localhost:6969` in your browser.

---

## 3. Method B: Native Local Setup (Step-by-Step)

If developing locally without Docker:

### Step 1: Clone Repository & Virtual Environment
```bash
# Clone
git clone https://github.com/your-org/videotester.git
cd videotester/backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Windows (Command Prompt):
venv\Scripts\activate.bat
# macOS / Linux:
source venv/bin/activate
```

### Step 2: Install Python Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables (.env)
Create `backend/.env`:
```env
# Required for speech transcription
GROQ_API_KEY=gsk_your_groq_api_key

# Required for transcript phonetic correction & Image analysis
OPENAI_API_KEY=sk-proj_your_openai_api_key

# Redis connection
REDIS_URL=redis://localhost:6379/0

# Server config
PORT=6969
HOST=0.0.0.0

# Webhook Callback settings (Optional for local dev)
BACKEND_BASE_URL=http://127.0.0.1:8080
CALLBACK_SECRET=local_dev_secret
```

### Step 4: Start Redis Broker
Start Redis on port 6379:
```bash
redis-server
# OR via standalone docker container:
docker run -d -p 6379:6379 --name redis-dev redis:7-alpine
```

### Step 5: Start Celery Worker

> [!IMPORTANT]
> **Windows Users**: Celery's default `prefork` process pool is not supported on Windows and will hang or error out. You **must** specify `--pool=solo`.

**Windows (PowerShell with venv activated):**
```powershell
cd backend
python -m celery -A worker.celery worker --loglevel=info --pool=solo
```

**macOS / Linux:**
```bash
cd backend
python -m celery -A worker.celery worker --loglevel=info --concurrency=2
```

### Step 6: Start FastAPI Server
In another terminal (with venv activated):
```bash
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 6969
```

---

## 4. Verifying Your Installation

1. **Check API & Redis Connectivity**:
   Visit `http://localhost:6969/api/health` in your browser. Expected response:
   ```json
   {
     "status": "healthy",
     "timestamp": "2026-10-01T13:30:00.000000",
     "redis": "connected"
   }
   ```
2. **Access the Web Dashboard**:
   Visit `http://localhost:6969`.
3. **Run a Test Upload**:
   - Enter a brand name (e.g. `boAt` or `Samsung`).
   - Drag and drop a short video (`.mp4`) or image (`.jpg`/`.png`).
   - Watch the progress bar increment (`Uploading` $\rightarrow$ `Analyzing video` $\rightarrow$ `Analyzing audio` $\rightarrow$ `Waiting for transcript`).
   - Inspect the generated score gauge, technical specifications, and transcript tags.

---

## 5. Common Issues & Troubleshooting

### Issue 1: `FFmpeg/FFprobe not found in PATH`
- **Cause**: FFmpeg executable is not installed or not added to system environment variables.
- **Fix**: Run `ffmpeg -version` in your terminal. If unrecognized, install FFmpeg and restart your terminal.

### Issue 2: Celery Worker hangs or crashes on Windows
- **Cause**: Using default billiard `prefork` pool on Windows.
- **Fix**: Launch Celery with `--pool=solo` parameter:
  ```powershell
  python -m celery -A worker.celery worker --loglevel=info --pool=solo
  ```

### Issue 3: Redis connection refused (`Error 10061` / `ConnectionRefusedError`)
- **Cause**: Redis server is not running on `localhost:6379`.
- **Fix**: Start Redis via `docker run -d -p 6379:6379 redis:7-alpine` or check if `REDIS_URL` in `.env` matches your Redis host.

### Issue 4: `GROQ_API_KEY not found` or `Whisper failed`
- **Cause**: Missing or invalid `GROQ_API_KEY` in `.env`.
- **Fix**: Obtain an API key from [console.groq.com](https://console.groq.com/) and paste it into `backend/.env`.

### Issue 5: Port 6969 already in use
- **Fix**:
  - Windows: `Stop-Process -Id (Get-NetTCPConnection -LocalPort 6969).OwningProcess -Force`
  - Linux/Mac: `kill -9 $(lsof -t -i:6969)`
  - Or set `PORT=7000` in `.env`.
