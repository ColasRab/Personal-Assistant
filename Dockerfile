FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY --chown=app:app server.py ./
COPY --chown=app:app mcp_auth.py ./
COPY --chown=app:app mcp_tools ./mcp_tools

USER app

EXPOSE 8000

CMD ["python", "server.py"]
