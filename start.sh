#!/bin/bash

# AI Media Quality Validator - Start Script

echo "🎬 Starting AI Media Quality Validator..."

# Navigate to backend directory
cd "$(dirname "$0")/backend"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "📦 Installing dependencies..."
pip install -q -r requirements.txt

# Start the server
echo ""
echo "🚀 Server starting at http://localhost:6969"
echo "📊 Open this URL in your browser to access the dashboard"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

python -m uvicorn main:app --reload --host 0.0.0.0 --port 6969
