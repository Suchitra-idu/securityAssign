FROM python:3.12-slim

RUN adduser --system --group --home /app app
WORKDIR /app

COPY shared_security /app/shared_security
COPY auth_service /app/auth_service

RUN pip install --no-cache-dir /app/shared_security /app/auth_service

USER app

EXPOSE 8000

CMD ["uvicorn", "auth_service.infrastructure.main:app", "--host", "0.0.0.0", "--port", "8000"]
