#!/bin/bash
# Start script for Render deployment.
# In Render dashboard: Build Command = pip install -r requirements.txt
#                      Start Command = bash start.sh

uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
