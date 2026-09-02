FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY services/hello-world ./services/hello-world
# Install uv
RUN pip install uv
RUN uv sync --no-dev
WORKDIR /app/services/hello-world
CMD ["uv", "run", "python", "-m", "hello_world.main"]
