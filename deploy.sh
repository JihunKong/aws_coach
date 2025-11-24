#!/bin/bash

# Deploy script for coaching-bot on EC2
set -e

echo "🚀 Starting deployment..."

# Pull latest code (if using git)
if [ -d ".git" ]; then
    echo "📥 Pulling latest code..."
    git pull origin main
fi

# Check .env file
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo "Please create .env file with required environment variables"
    echo "Use .env.example as a template"
    exit 1
fi

# Build Docker image
echo "🔨 Building Docker image..."
docker-compose build --no-cache

# Stop old containers
echo "🛑 Stopping old containers..."
docker-compose down

# Start new containers
echo "▶️  Starting new containers..."
docker-compose up -d

# Health check
echo "🏥 Checking health..."
sleep 5
for i in {1..10}; do
    if curl -f http://localhost:5000/health > /dev/null 2>&1; then
        echo ""
        echo "✅ Deployment successful!"
        docker-compose logs --tail=50
        exit 0
    fi
    echo "Waiting for service to be ready... ($i/10)"
    sleep 3
done

echo "❌ Health check failed!"
docker-compose logs
exit 1
