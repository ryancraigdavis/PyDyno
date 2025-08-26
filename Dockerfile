# Dockerfile for PyDyno testing
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files needed for pip install
COPY pyproject.toml README.md LICENSE ./
COPY uv.lock* ./

# Copy source code
COPY src/ ./src/
COPY tests/ ./tests/

# Install PyDyno in editable mode with all optional dependencies
RUN pip install --no-cache-dir -e ".[all]"

# Set Python path
ENV PYTHONPATH=/app

# Default command
CMD ["python", "-m", "src.pydyno.scripts.test_integration"]