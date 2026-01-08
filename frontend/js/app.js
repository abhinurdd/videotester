/**
 * AI Media Quality Validator - Frontend Application
 * Handles file upload, analysis polling, and results display
 */

// API Configuration
const API_BASE_URL = 'http://localhost:6969/api';

// DOM Elements
const uploadZone = document.getElementById("uploadZone");
const fileInput = document.getElementById("fileInput");
const uploadSection = document.getElementById("uploadSection");
const progressContainer = document.getElementById("progressContainer");
const resultsSection = document.getElementById("resultsSection");
const historyList = document.getElementById("historyList");
const analyzeAnother = document.getElementById("analyzeAnother");

// Progress elements
const progressFill = document.getElementById("progressFill");
const progressText = document.getElementById("progressText");
const fileName = document.getElementById("fileName");
const fileStatus = document.getElementById("fileStatus");

// Score elements
const overallScore = document.getElementById("overallScore");
const overallGrade = document.getElementById("overallGrade");
const gaugeFill = document.getElementById("gaugeFill");
const videoScore = document.getElementById("videoScore");
const audioScore = document.getElementById("audioScore");
const temporalScore = document.getElementById("temporalScore");
const videoScoreBar = document.getElementById("videoScoreBar");
const audioScoreBar = document.getElementById("audioScoreBar");
const temporalScoreBar = document.getElementById("temporalScoreBar");

// Spec elements
const specResolution = document.getElementById("specResolution");
const specBitrate = document.getElementById("specBitrate");
const specCodec = document.getElementById("specCodec");
const specFps = document.getElementById("specFps");
const specDuration = document.getElementById("specDuration");
const specSampleRate = document.getElementById("specSampleRate");
const specChannels = document.getElementById("specChannels");
const specLufs = document.getElementById("specLufs");

// Insights
const insightsList = document.getElementById("insightsList");

// State
let currentFileId = null;
let pollInterval = null;
let analysisStartTime = null;

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  loadHistory();
  
  // Prevent default drag behaviors on window to prevent opening files in browser
  window.addEventListener("dragover", function(e) {
    e = e || event;
    e.preventDefault();
  }, false);
  window.addEventListener("drop", function(e) {
    e = e || event;
    e.preventDefault();
  }, false);
});

function setupEventListeners() {
  // Upload zone click
  uploadZone.addEventListener("click", () => fileInput.click());

  // File input change
  fileInput.addEventListener("change", handleFileSelect);

  // Drag and drop
  uploadZone.addEventListener("dragover", handleDragOver);
  uploadZone.addEventListener("dragleave", handleDragLeave);
  uploadZone.addEventListener("drop", handleDrop);

  // Analyze another
  analyzeAnother.addEventListener("click", showUploadSection);
  
  // Try again
  const tryAgainBtn = document.getElementById('tryAgainBtn');
  if (tryAgainBtn) {
    tryAgainBtn.addEventListener('click', () => {
        showUploadSection();
        tryAgainBtn.style.display = 'none';
        
        // Reset styles
        const fileStatus = document.getElementById("fileStatus");
        const progressFill = document.getElementById("progressFill");
        fileStatus.style.color = "";
        progressFill.style.background = "";
    });
  }
}

function handleDragOver(e) {
  e.preventDefault();
  e.stopPropagation();
  uploadZone.classList.add("drag-over");
}

function handleDragLeave(e) {
  e.preventDefault();
  e.stopPropagation();
  uploadZone.classList.remove("drag-over");
}

function handleDrop(e) {
  e.preventDefault();
  e.stopPropagation();
  uploadZone.classList.remove("drag-over");

  const files = e.dataTransfer.files;
  if (files.length > 0) {
    uploadFile(files[0]);
  }
}

function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) {
    uploadFile(file);
  }
}

async function uploadFile(file) {
  // Validate file type
  const allowedTypes = ["video/", "audio/"];
  const isAllowed = allowedTypes.some((type) => file.type.startsWith(type));

  if (!isAllowed) {
    alert("Please upload a video or audio file.");
    return;
  }

  // Validate Brand Name (Mandatory)
  const brandInput = document.getElementById("brandInput");
  if (!brandInput || !brandInput.value.trim()) {
    alert("⚠️ Brand Name is required for compliance check.\nPlease enter a brand name before uploading.");
    if (brandInput) {
        brandInput.focus();
        brandInput.style.borderColor = "#ef4444";
        // Reset border after 3 seconds
        setTimeout(() => brandInput.style.borderColor = "var(--border-color)", 3000);
    }
    return;
  }

  // Set start time
  analysisStartTime = Date.now();
  console.log("Start time set:", analysisStartTime);

  // Show progress
  showProgress(file.name);
  console.log("Starting upload for:", file.name);

  try {
    const formData = new FormData();
    formData.append("file", file);
    
    // Add brand name if provided
    const brandInput = document.getElementById("brandInput");
    if (brandInput && brandInput.value.trim()) {
        formData.append("brand_name", brandInput.value.trim());
    }

    // Upload with progress tracking
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        const percent = Math.round((e.loaded / e.total) * 100);
        updateProgress(Math.min(percent, 30), "Uploading...");
      }
    });

    xhr.onload = function () {
      console.log("Upload response status:", xhr.status);
      if (xhr.status === 200) {
        const response = JSON.parse(xhr.responseText);
        currentFileId = response.file_id;
        console.log("Upload success, file ID:", currentFileId);
        updateProgress(30, "Upload complete, analyzing...");
        startPolling(response.file_id);
      } else {
        console.error("Upload failed with status:", xhr.status, xhr.statusText);
        showError("Upload failed: " + xhr.statusText);
      }
    };

    xhr.onerror = function () {
      console.error("Network error during upload");
      showError("Network error. Please check if the server is running.");
    };

    xhr.open("POST", `${API_BASE_URL}/upload`);
    xhr.send(formData);
  } catch (error) {
    console.error("Exception during upload:", error);
    showError("Error uploading file: " + error.message);
  }
}

function showProgress(name) {
  uploadZone.style.display = "none";
  progressContainer.style.display = "block";
  fileName.textContent = name;
  updateProgress(0, "Uploading...");
}

function updateProgress(percent, status) {
  progressFill.style.width = `${percent}%`;
  progressText.textContent = `${percent}%`;
  fileStatus.textContent = status;
}

function startPolling(fileId) {
  pollInterval = setInterval(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/status/${fileId}`);
      const data = await response.json();

      if (data.status === "processing") {
        // Map backend progress (0-100) to display progress (30-95)
        const displayProgress = 30 + data.progress * 0.65;
        updateProgress(Math.round(displayProgress), data.message);
      } else if (data.status === "completed") {
        stopPolling();
        updateProgress(100, "Complete!");
        await loadResults(fileId);
      } else if (data.status === "failed") {
        stopPolling();
        showError(data.message || "Analysis failed");
      }
    } catch (error) {
      stopPolling();
      showError("Error checking status: " + error.message);
    }
  }, 1000);
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

async function loadResults(fileId) {
  try {
    const response = await fetch(`${API_BASE_URL}/analyze/${fileId}`);
    const data = await response.json();

    if (response.status === 202) {
      // Still processing
      return;
    }

    if (!response.ok) {
      throw new Error(data.detail || "Failed to load results");
    }

    displayResults(data);
    loadHistory();
  } catch (error) {
    showError("Error loading results: " + error.message);
  }
}

function displayResults(data) {
  // Calculate processing time
  const processingTimeEl = document.getElementById("processingTime");
  if (processingTimeEl) {
      if (analysisStartTime) {
        const duration = (Date.now() - analysisStartTime) / 1000;
        processingTimeEl.textContent = `Results processed in ${duration.toFixed(1)} seconds`;
      } else {
        processingTimeEl.textContent = "";
      }
  }

  // Hide upload, show results
  uploadSection.style.display = "none";
  resultsSection.style.display = "flex";
  resultsSection.classList.add("animate-in");

  // Animate overall score gauge
  const score = data.overall_score || 0;
  animateGauge(score, data.grade);

  // Update sub-scores
  animateScore(videoScore, videoScoreBar, data.video_score || 0);
  animateScore(audioScore, audioScoreBar, data.audio_score || 0);
  animateScore(audioScore, audioScoreBar, data.audio_score || 0);
  // Temporal score removed
  
  // Update Brand Compliance
  const brandCard = document.getElementById("brandCard");
  const brandCompliance = data.brand_compliance;
  
  if (brandCard) {
      if (brandCompliance && brandCompliance.target_brand) {
          brandCard.style.display = "block";
          document.getElementById("targetBrandName").textContent = brandCompliance.target_brand;
          
          const count = brandCompliance.mention_count || 0;
          const countEl = document.getElementById("brandCount");
          countEl.textContent = count;
          
          const badge = document.getElementById("brandBadge");
          if (count > 0) {
              badge.textContent = "PASS";
              badge.style.background = "#22c55e";
              badge.style.color = "white";
          } else {
              badge.textContent = "WARNING";
              badge.style.background = "#eab308"; // yellow/orange
              badge.style.color = "black";
          }
          
          const timestampContainer = document.getElementById("brandTimestamps");
          timestampContainer.innerHTML = "";
          if (brandCompliance.timestamps && brandCompliance.timestamps.length > 0) {
              brandCompliance.timestamps.forEach(ts => {
                 const tag = document.createElement("span");
                 tag.style.background = "rgba(255,255,255,0.1)";
                 tag.style.color = "var(--text-primary)";
                 tag.style.padding = "4px 8px";
                 tag.style.borderRadius = "4px";
                 tag.style.fontSize = "0.85rem";
                 tag.textContent = formatDuration(ts);
                 timestampContainer.appendChild(tag);
              });
          }
          
          // Display full transcript if available
          const transcriptCard = document.getElementById("transcriptCard");
          const transcriptContent = document.getElementById("transcriptContent");
          if (transcriptCard && transcriptContent && brandCompliance.full_transcript && brandCompliance.full_transcript.length > 0) {
              transcriptCard.style.display = "block";
              const brandLower = (brandCompliance.target_brand || "").toLowerCase();
              
              let transcriptHtml = brandCompliance.full_transcript.map(segment => {
                  let text = segment.text;
                  
                  // Highlight brand mentions (case insensitive)
                  if (brandLower) {
                      const regex = new RegExp(`(${brandLower.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
                      text = text.replace(regex, '<span style="background: #22c55e; color: white; padding: 1px 4px; border-radius: 3px; font-weight: 600;">$1</span>');
                  }
                  
                  return `<div style="margin-bottom: 8px;">
                      <span style="color: #60a5fa; font-weight: 500; margin-right: 8px;">[${formatDuration(segment.time)}]</span>
                      <span>${text}</span>
                  </div>`;
              }).join('');
              
              transcriptContent.innerHTML = transcriptHtml;
          } else if (transcriptCard) {
              transcriptCard.style.display = "none";
          }
      } else {
          brandCard.style.display = "none";
          // Also hide transcript card if no brand compliance
          const transcriptCard = document.getElementById("transcriptCard");
          if (transcriptCard) transcriptCard.style.display = "none";
      }
  }

  // Update technical specs
  const specs = data.technical_specs || {};
  specResolution.textContent = specs.resolution || "--";
  specBitrate.textContent = specs.bitrate_kbps
    ? `${specs.bitrate_kbps} kbps`
    : "--";
  specCodec.textContent = specs.codec?.toUpperCase() || "--";
  specFps.textContent = specs.fps ? `${specs.fps} fps` : "--";
  specDuration.textContent = formatDuration(specs.duration_seconds);
  specSampleRate.textContent = specs.audio_sample_rate
    ? `${specs.audio_sample_rate} Hz`
    : "--";
  specChannels.textContent = specs.audio_channels || "--";
  specLufs.textContent = specs.loudness_lufs
    ? `${specs.loudness_lufs.toFixed(1)} LUFS`
    : "--";

  // Update insights
  displayInsights(data.issues || []);
}

function animateGauge(score, grade) {
  const circumference = 2 * Math.PI * 85; // radius is 85
  const offset = circumference - (score / 100) * circumference;

  // Reset
  gaugeFill.style.strokeDashoffset = circumference;
  overallScore.textContent = "0";
  overallGrade.textContent = "--";

  // Determine color class
  gaugeFill.classList.remove("score-high", "score-medium", "score-low");
  if (score >= 70) {
    gaugeFill.classList.add("score-high");
  } else if (score >= 40) {
    gaugeFill.classList.add("score-medium");
  } else {
    gaugeFill.classList.add("score-low");
  }

  // Animate
  setTimeout(() => {
    gaugeFill.style.strokeDashoffset = offset;

    // Animate number
    animateNumber(overallScore, 0, Math.round(score), 1000);

    // Show grade after delay
    setTimeout(() => {
      overallGrade.textContent = grade || "--";
    }, 500);
  }, 100);
}

function animateScore(element, barElement, score) {
  element.textContent = "0";
  barElement.style.width = "0%";

  setTimeout(() => {
    animateNumber(element, 0, Math.round(score), 800);
    barElement.style.width = `${score}%`;
  }, 200);
}

function animateNumber(element, start, end, duration) {
  const startTime = performance.now();

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);

    // Ease out
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = Math.round(start + (end - start) * eased);

    element.textContent = current;

    if (progress < 1) {
      requestAnimationFrame(update);
    }
  }

  requestAnimationFrame(update);
}

function displayInsights(issues) {
  if (!issues || issues.length === 0) {
    insightsList.innerHTML = `
            <div class="insights-empty">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>
                    <polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
                <p>No issues detected</p>
            </div>
        `;
    return;
  }

  insightsList.innerHTML = issues
    .map(
      (issue) => `
        <div class="insight-item severity-${issue.severity || "low"}">
            <div class="insight-icon">
                ${getIssueIcon(issue.severity)}
            </div>
            <div class="insight-content">
                <div class="insight-header">
                    <span class="insight-type">${issue.type || "Unknown"}</span>
                </div>
                <div class="insight-message">${
                  issue.message || "Issue detected"
                }</div>
                ${
                  issue.recommendation
                    ? `<div class="insight-recommendation">${issue.recommendation}</div>`
                    : ""
                }
            </div>
        </div>
    `
    )
    .join("");
}

function getIssueIcon(severity) {
  switch (severity) {
    case "high":
      return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>`;
    case "medium":
      return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
                <line x1="12" y1="9" x2="12" y2="13"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>`;
    default:
      return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="16" x2="12" y2="12"/>
                <line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>`;
  }
}

function formatDuration(seconds) {
  if (!seconds || isNaN(seconds)) return "--";

  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);

  if (mins > 0) {
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }
  return `${secs}s`;
}

async function loadHistory() {
  try {
    const response = await fetch(`${API_BASE_URL}/history`);
    const data = await response.json();

    displayHistory(data.files || []);
  } catch (error) {
    console.error("Error loading history:", error);
  }
}

function displayHistory(files) {
  if (!files || files.length === 0) {
    historyList.innerHTML = `
            <div class="history-empty">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="3" y="3" width="18" height="18" rx="2"/>
                    <path d="M3 9h18"/>
                    <path d="M9 21V9"/>
                </svg>
                <p>No files analyzed yet</p>
            </div>
        `;
    return;
  }

  historyList.innerHTML = files
    .map((file) => {
      const score = file.overall_score;
      const scoreClass =
        score >= 70 ? "score-high" : score >= 40 ? "score-medium" : "score-low";
      const date = new Date(file.upload_time);
      const dateStr = date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      });

      return `
            <div class="history-item ${
              file.id === currentFileId ? "active" : ""
            }" 
                 onclick="loadFileById(${file.id})">
                <div class="history-score ${scoreClass}">
                    ${score !== null ? Math.round(score) : "--"}
                </div>
                <div class="history-info">
                    <div class="history-name">${file.filename}</div>
                    <div class="history-date">${dateStr}</div>
                </div>
            </div>
        `;
    })
    .join("");
}

async function loadFileById(fileId) {
  currentFileId = fileId;
  analysisStartTime = null; // Reset timer for history items
  uploadSection.style.display = "none";
  resultsSection.style.display = "none";
  progressContainer.style.display = "none";

  // Show loading state
  uploadZone.style.display = "none";
  progressContainer.style.display = "block";
  updateProgress(50, "Loading results...");

  await loadResults(fileId);
}

function showUploadSection() {
  resultsSection.style.display = "none";
  uploadSection.style.display = "flex";
  progressContainer.style.display = "none";
  uploadZone.style.display = "block";
  fileInput.value = "";
  currentFileId = null;
}

function showError(message) {
  stopPolling();
  fileStatus.textContent = message;
  fileStatus.style.color = "#ef4444";
  progressFill.style.background = "#ef4444";

    // Log error
    console.error(message);
    
    // Show try again button if it exists, or just let user reload for now
    // We will add a Try Again button in the next step
    const tryAgainBtn = document.getElementById('tryAgainBtn');
    if (tryAgainBtn) {
        tryAgainBtn.style.display = 'inline-block';
    }
}

// Make loadFileById available globally
window.loadFileById = loadFileById;
