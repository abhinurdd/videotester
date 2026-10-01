# Docker & Deployment Commands for VideoTester

This document provides complete instructions for building, running, and managing the AI Media Quality Validator services locally and on AWS EC2 (including ARM64 / Graviton `t4g` instances).

---

## 1. Architecture Overview (Containers)

The system runs as three cooperating services:
1. **`content-analysis-redis`**: In-memory broker and status cache (Redis 7 Alpine, LRU memory-capped at 128MB).
2. **`content-analysis-api`**: FastAPI HTTP REST API server handling file uploads, R2 requests, and status queries on port `6969`.
3. **`content-analysis-worker`**: Celery worker running asynchronous video/audio/image analysis, Groq Whisper transcription, GPT-4o vision/transcript restoration, and webhook callbacks.

---

## 2. Multi-Platform Build & Push (`build_and_push.py`)

The project includes an automated build script targeting **ARM64** (`linux/arm64`) architectures (specifically optimized for AWS EC2 `t4g` Graviton instances) and pushing directly to Docker Hub (`technurdd/content-analysis`).

### Prerequisites
Log in to Docker Hub:
```bash
docker login
```

### Build and Push Development Image
```bash
python build_and_push.py dev
```
*Builds and pushes tag `technurdd/content-analysis:dev` with inline cache.*

### Build and Push Production Image
```bash
python build_and_push.py prod
```
*Builds and pushes tag `technurdd/content-analysis:prod` with inline cache.*

### Manual Local Build (Current System Architecture)
```bash
# Build production image locally
docker build -t technurdd/content-analysis:prod -f Dockerfile .

# Build development image locally
docker build -t technurdd/content-analysis:dev -f Dockerfile .
```

---

## 3. Docker Compose Workflows

### A. Local Development (Hot-Reload & Concurrency 2)
Uses `docker-compose.dev.yml` with source directory volume mounts (`./backend` and `./frontend`):

```bash
# Start all dev services in background
docker compose -f docker-compose.dev.yml up -d

# Start with image rebuild
docker compose -f docker-compose.dev.yml up -d --build

# View dev logs
docker compose -f docker-compose.dev.yml logs -f

# View worker logs only
docker compose -f docker-compose.dev.yml logs -f worker

# Stop dev environment
docker compose -f docker-compose.dev.yml down
```

### B. Production Deployment (EC2 / Server)
Uses `docker-compose.yml` with production settings:
- Worker concurrency set to `1` (single CPU bound worker) with `--max-tasks-per-child=10` to eliminate memory leaks from OpenCV / Librosa.
- Persistent SQLite database mount (`./media_validator.db:/app/backend/media_validator.db`).
- Persistent/shared uploads mount (`./uploads:/app/backend/uploads`).

```bash
# Pull latest production images
docker compose pull

# Launch production stack in background
docker compose up -d

# Build locally and launch
docker compose up -d --build

# Follow combined logs
docker compose logs -f

# Follow API or Worker logs specifically
docker compose logs -f api
docker compose logs -f worker
```

---

## 4. EC2 Instance Setup & Deployment Guide

### 1. Launch EC2 Instance
- **Recommended AMI**: Amazon Linux 2023 or Ubuntu 22.04 LTS (ARM64 / aarch64 architecture for `t4g.small` or `t4g.medium`).
- **RAM**: Minimum 2 GB (e.g. `t4g.small`).

### 2. Configure Security Group
Ensure inbound rules permit:
- **Port 22** (SSH): Restricted to your IP.
- **Port 6969** (FastAPI / Dashboard): Accessible for web client access or restricted to your reverse proxy / VPC.

### 3. Connect via SSH
```bash
ssh -i /path/to/your-key.pem ec2-user@<YOUR-EC2-PUBLIC-IP>
```

### 4. Install Docker & Docker Compose
**Amazon Linux 2023 / Amazon Linux 2:**
```bash
sudo dnf update -y || sudo yum update -y
sudo dnf install -y docker || sudo yum install -y docker
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker ec2-user

# Install Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m) -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Log out and log back in for docker group to apply
exit
```

### 5. Deploy Project Files
Create project directory on EC2:
```bash
mkdir -p ~/videotester
cd ~/videotester
```

Copy your configuration files (`docker-compose.yml`, `.env`):
```bash
# Ensure .env is populated with required credentials
cat << 'EOF' > .env
GROQ_API_KEY=your_groq_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
BACKEND_BASE_URL=https://api.yourdomain.com
CALLBACK_SECRET=your_secret_waf_token
EOF
```

### 6. Pull & Start Services
```bash
docker compose pull
docker compose up -d
```

### 7. Verify Operation
```bash
# Check status of containers
docker compose ps

# Check API health
curl http://localhost:6969/api/health
```

---

## 5. Maintenance & Diagnostics

### Container Lifecycle Commands
```bash
# Restart entire stack
docker compose restart

# Restart worker only (e.g. after model or analyzer tweak)
docker compose restart worker

# Stop all containers
docker compose stop

# Tear down containers (preserving volumes)
docker compose down

# Tear down containers and wipe anonymous volumes
docker compose down -v
```

### Database Management
The SQLite database `media_validator.db` is persisted on the host:
```bash
# Reset database (stops services, removes DB, restarts)
docker compose stop
rm -f media_validator.db
docker compose up -d
```

### Redis Inspection
```bash
# Connect to running Redis CLI
docker compose exec redis redis-cli

# Inside redis-cli:
# Check connection
PING
# Monitor incoming task queues and status updates
KEYS "status:*"
INFO memory
```

### Clean Up Disk Space
```bash
# Prune unused docker images and dangling layers
docker image prune -a --force

# Inspect upload directory disk usage
du -sh uploads/
```

