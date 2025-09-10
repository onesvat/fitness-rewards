FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the project into the image
ADD . /app

# Sync the project into a new environment, asserting the lockfile is up to date
WORKDIR /app

RUN uv sync --locked

# Install the package in editable mode so Python can find the modules
RUN uv pip install -e .

# Create data directory for SQLite database and configs
RUN mkdir -p /app/data

# Expose the port the app runs on
EXPOSE 8000

# Set the default command to run the main server
CMD ["uv", "run", "python", "-m", "fitness_rewards.main"]