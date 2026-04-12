FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir uv
COPY shared/ ./shared/
COPY agents/code_analyst/ ./agent/
RUN uv pip install --system --no-cache ./shared ./agent

FROM python:3.12-slim
RUN useradd -m -u 1000 app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
WORKDIR /app
COPY --chown=app:app agents/code_analyst/app ./app/
USER app
EXPOSE 8003
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8003/health')" || exit 1
CMD ["uvicorn", "app.server:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8003"]
