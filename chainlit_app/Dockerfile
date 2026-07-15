# Base image
FROM python:3.12-slim

# Set environment variables for better behavior
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Set working directory
WORKDIR /chainlit_app

# Install system dependencies
# These are minimal dependencies; modify as needed for your app.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy only the requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir uv
RUN uv pip install --system --no-cache -r requirements.txt

# Copy the application code
COPY ./ /chainlit_app/

# Expose the port Chainlit will run on
EXPOSE 8000

# Command to run Chainlit
CMD ["python", "-m", "chainlit", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]
