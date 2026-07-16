#!/bin/bash

# Start Uvicorn server
exec gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:${PORT:-6100} --preload app.main:app --timeout 120 --keep-alive 120 --log-level debug
