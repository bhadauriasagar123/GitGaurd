# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS build
WORKDIR /w
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM base AS runtime
# non-root, read-only-friendly image
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /install /usr/local
WORKDIR /srv
COPY app ./app
COPY static ./static
COPY alembic.ini .
COPY alembic ./alembic
USER 10001
ENV ENV=production PORT=8000 WEB_CONCURRENCY=2
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --no-server-header --proxy-headers --forwarded-allow-ips '*' --timeout-keep-alive 30 --timeout-graceful-shutdown 20"]
