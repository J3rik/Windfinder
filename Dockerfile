# Windfinder - Streamlit dashboard + alert worker.
#
# The dashboard is the default command. The alert worker runs as a separate
# process (see docker-compose.yml) because it is a long-running loop.
FROM python:3.11-slim

# Unbuffered output so `docker compose logs` shows output immediately, and no
# .pyc files to keep the image clean.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer is cached while application code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application files.
COPY app.py alert_service.py profiles.py wind_forecast.py ./
COPY .streamlit/ ./.streamlit/

# NOTE: users.json is intentionally NOT copied. It is a bind-mounted volume so
# profiles live on the host. Compose creates the host file if it is missing
# (which is why users.json must exist as a file before `up` - see README).

EXPOSE 8501

# Lightweight liveness check: Streamlit serves HTTP on /_stcore/health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--browser.gatherUsageStats=false"]
