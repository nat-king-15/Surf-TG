# ----------------------------------------------------------------------
# Stage 1: Build Stage (Only includes tools necessary for installation)
# ----------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Install build dependencies (for compiling C extensions like tgcrypto, ntgcalls).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        cmake \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy requirement file first to leverage Docker layer caching
COPY requirements.txt .

# Install pip and uv
RUN pip install -U pip uv

# Install Python dependencies.
RUN uv pip install --system --no-cache-dir -r requirements.txt

# Copy the rest of the application source code
COPY . /app

# ----------------------------------------------------------------------
# Stage 2: Final Stage (Minimal Runtime Image)
# ----------------------------------------------------------------------
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Install necessary runtime system dependencies:
# 1. 'bash' for your CMD ["bash", "surf-tg.sh"].
# 2. 'git' because your deployed application/script needs it at runtime.
# 3. 'ffmpeg' for pytgcalls VC streaming.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        git \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy the installed Python dependencies from the 'builder' stage
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy the application source code
COPY --from=builder /app /app

# Command to run when the container starts
CMD ["bash", "surf-tg.sh"]
