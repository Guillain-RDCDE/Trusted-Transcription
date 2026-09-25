# The operator commands, nothing else: no engine, no API client.
#   docker build -t tt .
#   docker run --rm tt cost 60
#   docker run --rm -v "$PWD/corpus/sample:/data" tt detect /data/silence_hallucination.json
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
RUN pip install --no-cache-dir . && rm -rf /app

WORKDIR /data
ENTRYPOINT ["tt"]
CMD ["--help"]
