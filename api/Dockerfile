# Built from the project root so the dashboard can be copied in alongside the
# API. A build context of ./api alone cannot reach ../dashboard.
FROM python:3.12-slim
WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/main.py .
COPY dashboard /dashboard

RUN useradd -u 10001 -m app
USER app

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
