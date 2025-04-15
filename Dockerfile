# Use official Python base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy the project files
COPY p2p_node.py .  
COPY README.md .
COPY mychat.db .
COPY peers.txt .

# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# Default command; override with CMD in docker-compose or `docker run`
CMD ["python", "p2p_node.py"]