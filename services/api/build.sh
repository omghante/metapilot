#!/usr/bin/env bash
# Build script for Render

set -o errexit  # Exit on error

# Install dependencies using pip (Render uses pip by default)
pip install --upgrade pip
pip install -r requirements.txt

# Collect static files
python manage.py collectstatic --noinput

# Run database migrations
python manage.py migrate
