# API Reference & Integration Guide

The AI Media Quality Validator provides a RESTful API built on FastAPI. It supports synchronous ingestion with asynchronous background execution via Celery, real-time status polling, and webhook delivery.

Base URL: `http://<host>:6969` (or configured reverse proxy)

---

## Table of Contents
1. [General Concepts & Headers](#1-general-concepts--headers)
2. [Endpoints](#2-endpoints)
   - [Health Check](#get-apihealth)
   - [Direct Media Upload](#post-apiupload)
   - [Cloudflare R2 Direct Ingestion](#post-apianalyze-r2)
   - [Check Task Status](#get-apistatusfile_id)
   - [Retrieve Full Analysis Results](#get-apianalyzefile_id)
   - [Upload History](#get-apihistory)
   - [Delete File & Analysis](#delete-apifilesfile_id)
3. [Webhook Callback Specification](#3-webhook-callback-specification)
4. [Error Handling & Status Codes](#4-error-handling--status-codes)

---

## 1. General Concepts & Headers

- **Asynchronous Task Model**: Long-running media jobs return immediately with a `file_id` and initial state `uploaded` or `queued`. Clients should either:
  1. Poll `GET /api/status/{file_id}` or `GET /api/analyze/{file_id}`, or
  2. Provide a `callback_url` to receive a webhook notification when finished.
- **Cache-Control**: All API responses pass through `NoCacheMiddleware` to prevent browser or intermediate proxy caching (`Cache-Control: no-cache, no-store, must-revalidate`).
- **CORS**: Configured with open access (`*`) for cross-origin frontend dashboard integration.

---

## 2. Endpoints

### `GET /api/health`
Checks API readiness and the live connection to the Redis broker.

#### Response
```json
{
  "status": "healthy",
  "timestamp": "2026-10-01T13:10:00.000000",
  "redis": "connected"
}
```
*If Redis is unreachable, `"redis": "disconnected"` is returned with status code 200.*

---

### `POST /api/upload`
Uploads a local media file (video, audio, or image) directly as multipart form data.

#### Request Headers
- `Content-Type: multipart/form-data`

#### Form Parameters
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `file` | Binary File | **Yes** | Supported formats: `.mp4`, `.mkv`, `.avi`, `.mov`, `.webm`, `.flv`, `.wmv`, `.mpeg`, `.3gp`, `.m4v`, `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tiff`, `.heic`, `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac` |
| `brand_name` | String | No | Target brand name for compliance and mention verification |
| `content_type` | String | No | Media classification: `reel`, `short`, `post`, `story` (affects orientation & safe-area validation) |

#### Response (`200 OK`)
```json
{
  "file_id": 42,
  "filename": "sample_video.mp4",
  "file_size": 15420310,
  "status": "uploaded",
  "message": "File uploaded successfully, analysis queued..."
}
```

---

### `POST /api/analyze-r2`
Analyzes a media asset hosted on Cloudflare R2 or any accessible HTTP/HTTPS storage URL without uploading bytes through the browser.

#### Request Headers
- `Content-Type: application/json`

#### Request Body
```json
{
  "r2_url": "https://pub-your-bucket.r2.dev/campaigns/c123/submission_987.mp4",
  "campaign_id": "camp_2026_boat",
  "creator_id": "creator_5432",
  "brand_name": "boAt",
  "content_type": "reel",
  "callback_url": "https://api.myapp.com/api/v2/campaigns/callback"
}
```

| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `r2_url` | String | **Yes** | Direct or pre-signed URL to the media file |
| `campaign_id` | String | **Yes** | Client campaign identifier (passed back in callback) |
| `creator_id` | String | **Yes** | Client creator identifier (passed back in callback) |
| `brand_name` | String | No | Brand name to detect in audio/image |
| `content_type` | String | No | Hints media format (`reel`, `story`, `post`, etc.) |
| `callback_url` | String | No | Target webhook URL (defaults to `${BACKEND_BASE_URL}/api/v2/creators/campaigns/analysis-callback`) |

#### Response (`200 OK`)
```json
{
  "file_id": 43,
  "status": "queued",
  "message": "Analysis started from R2 URL"
}
```

---

### `GET /api/status/{file_id}`
Checks current analysis status and completion percentage. Reads from Redis cache first; falls back to SQLite.

#### Response (`200 OK`)
```json
{
  "file_id": 43,
  "status": "processing",
  "progress": 50,
  "message": "Analyzing audio..."
}
```

#### Status Lifecycle:
- `pending` (0%): File saved or R2 queued, awaiting Celery worker pickup.
- `processing` (5%): Downloading file from R2.
- `processing` (15-20%): Initializing analysis; parallel Groq transcription launched; analyzing video.
- `processing` (50%): Analyzing audio streams.
- `processing` (75%): Merging Whisper transcripts and GPT-4o entity corrections.
- `processing` (90%): Scoring and compiling final payload.
- `completed` (100%): Results stored in SQLite, Redis status set, callback executed.
- `failed` (0%): Error occurred (detailed in `message`).

---

### `GET /api/analyze/{file_id}`
Retrieves the complete evaluation report, technical specifications, and compliance details.

#### Responses:
- **`202 Accepted`**: Analysis still in progress:
  ```json
  {
    "file_id": 43,
    "status": "processing",
    "progress": 50,
    "message": "Analyzing audio..."
  }
  ```
- **`500 Internal Server Error`**: Analysis failed during worker execution:
  ```json
  {
    "file_id": 43,
    "status": "failed",
    "message": "Analysis failed: FFmpeg execution error"
  }
  ```
- **`200 OK`**: Complete analysis document:

```json
{
  "file_id": 43,
  "filename": "submission_987.mp4",
  "file_size": 15420310,
  "duration": 28.5,
  "upload_time": "2026-10-01 13:15:00",
  "overall_score": 88.4,
  "grade": "A",
  "video_score": 89.2,
  "audio_score": 87.6,
  "temporal_score": 94.0,
  "raw_metrics": {
    "video": {
      "resolution": { "width": 1080, "height": 1920 },
      "bitrate": 4500,
      "codec": "h264",
      "fps": 30.0,
      "duration": 28.5,
      "brisque_score": 78.4,
      "temporal_stability": 94.0,
      "frame_consistency": 98.2,
      "avg_brightness": 112.5
    },
    "audio": {
      "has_audio": true,
      "sample_rate": 44100,
      "duration": 28.5,
      "channels": 2,
      "snr_db": 34.2,
      "loudness_lufs": -14.2,
      "dynamic_range_db": 16.4,
      "has_clipping": false,
      "speech_clarity_score": 85.0,
      "frequency_balance": "balanced"
    },
    "brand_compliance": {
      "target_brand": "boAt",
      "mention_count": 2,
      "timestamps": [4.5, 18.2],
      "full_transcript": [
        {
          "time": 4.5,
          "hinglish": "yeh boAt ke headphones bohot badhiya hain",
          "english": "These boAt headphones are really great"
        }
      ]
    }
  },
  "issues": [
    {
      "type": "video",
      "severity": "low",
      "message": "Quality drops detected at: 12.0s",
      "recommendation": "There are brief moments where quality dips slightly."
    }
  ],
  "brand_compliance": {
    "target_brand": "boAt",
    "mention_count": 2,
    "timestamps": [4.5, 18.2],
    "full_transcript": [...]
  },
  "technical_status": {
    "short_side": 1080,
    "is_high_res": 1,
    "orientation": "portrait",
    "aspect_ratio": 0.56,
    "resolution_label": "1080p HD (Vertical/Reel)",
    "actual_resolution": "1080x1920",
    "safe_area_warning": 0,
    "aspect_ratio_message": "Perfectly suitable for reels (9:16 vertical).",
    "content_type_validated": "reels"
  },
  "technical_specs": {
    "resolution": "1080x1920",
    "bitrate_kbps": 4500,
    "codec": "h264",
    "fps": 30.0,
    "duration_seconds": 28.5,
    "audio_sample_rate": 44100,
    "audio_channels": 2,
    "loudness_lufs": -14.2
  }
}
```

---

### `GET /api/history`
Returns historical records with calculated scores and grades.

#### Query Parameters
- `limit` (int, default `20`): Maximum records to retrieve.

#### Response (`200 OK`)
```json
{
  "files": [
    {
      "id": 43,
      "filename": "submission_987.mp4",
      "file_size": 15420310,
      "duration": 28.5,
      "upload_time": "2026-10-01 13:15:00",
      "overall_score": 88.4,
      "video_score": 89.2,
      "audio_score": 87.6,
      "grade": "A"
    }
  ]
}
```

---

### `DELETE /api/files/{file_id}`
Deletes the temporary physical file on disk, purges the SQLite database entry (cascading to analyses), and deletes the Redis status key.

#### Response (`200 OK`)
```json
{
  "status": "deleted",
  "file_id": 43
}
```

---

## 3. Webhook Callback Specification

When a job is queued via `/api/analyze-r2`, the Celery worker automatically executes an HTTP `POST` request to the provided `callback_url` (or the fallback endpoint at `${BACKEND_BASE_URL}/api/v2/creators/campaigns/analysis-callback`).

### Headers Sent with Webhook
```http
POST /api/v2/creators/campaigns/analysis-callback HTTP/1.1
Host: api.myapp.com
Content-Type: application/json
Accept: application/json, text/plain, */*
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36
X-Callback-Secret: <CALLBACK_SECRET from .env>
```

> **Security Note:** If your destination server is protected by AWS WAF or Cloudflare, configure a rule to whitelist requests possessing the `X-Callback-Secret` header.

### Webhook JSON Payload
```json
{
  "file_id": 43,
  "campaign_id": "camp_2026_boat",
  "creator_id": "creator_5432",
  "status": "completed",
  "overall_score": 88.4,
  "video_score": 89.2,
  "audio_score": 87.6,
  "temporal_score": 94.0,
  "raw_metrics": { ... },
  "issues": [ ... ],
  "metadata": {
    "campaign_id": "camp_2026_boat",
    "creator_id": "creator_5432"
  }
}
```

---

## 4. Error Handling & Status Codes

| Code | Meaning | Common Cause |
| :---: | :--- | :--- |
| `200` | OK | Request succeeded synchronously |
| `202` | Accepted | Analysis in progress (poll again in 1s) |
| `400` | Bad Request | Unsupported media format or invalid input |
| `404` | Not Found | `file_id` does not exist in SQLite or Redis |
| `422` | Validation Error | Pydantic validation failure on request payload |
| `500` | Internal Error | FFmpeg failure, network failure downloading R2, or worker failure |
