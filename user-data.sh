#!/bin/bash
# EC2 User Data Script - Initial Setup for Coaching Bot

set -e

# Update system
apt-get update
apt-get install -y curl git

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
usermod -aG docker ubuntu
rm get-docker.sh

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Install Certbot
apt-get install -y certbot

# Create logs directory
mkdir -p /home/ubuntu/logs
chown ubuntu:ubuntu /home/ubuntu/logs

# Signal completion
touch /tmp/user-data-complete
