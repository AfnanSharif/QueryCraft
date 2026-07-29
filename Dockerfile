FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG REQUIREMENTS=requirements.txt
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r "$REQUIREMENTS"
COPY . .
RUN useradd --create-home appuser && mkdir -p /app/.local && chown -R appuser:appuser /app
USER appuser
EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
