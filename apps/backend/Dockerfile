FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc git libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Install CPU-only PyTorch first (smaller, no CUDA bloat)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        torch==2.4.1 \
        --index-url https://download.pytorch.org/whl/cpu

# Install pandas-ta from git (no PyPI release for Python 3.11)
RUN pip install --no-cache-dir \
    git+https://github.com/twopirllc/pandas-ta.git@development

# Install remaining dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 1000 trader && chown -R trader:trader /app
USER trader

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
