FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY pyproject.toml README.md requirements-hosted.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements-hosted.txt
COPY src ./src
RUN pip install --no-cache-dir --no-deps '.[hosted]' \
    && useradd --create-home --uid 10001 nativ
USER nativ
EXPOSE 8080
CMD ["nativ-mcp-http"]
