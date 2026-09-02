FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
# Install uv
RUN pip install uv
COPY hello_world /app/hello_world
RUN uv sync --no-dev
CMD ["uv", "run", "python", "-m", "hello_world.main"]
