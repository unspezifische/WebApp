# Dockerfile for Flask app with Python 3.11
FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY Flask/requirements.txt requirements.txt
RUN pip install -r requirements.txt --no-cache-dir

# Copy the rest of the application code
COPY Flask/ .

# Command to run the app with Gunicorn, using gevent with websocket support
CMD ["/bin/sh", "-c", "python bootstrap_database.py && exec gunicorn -w 1 --bind unix:/tmp/myapp.socket --reload --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker app:app"]
