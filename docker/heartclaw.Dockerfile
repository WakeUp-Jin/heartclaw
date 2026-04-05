FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy dependency file first for better caching
COPY pyproject.toml .

# Install dependencies
RUN uv pip install --system -e .

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "main.py"]
