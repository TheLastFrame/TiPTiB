FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

ARG APP_VERSION=0.25.0
ARG GIT_COMMIT=""
ARG BUILD_DATE=""

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN python -c "import json; from pathlib import Path; data = {'version': '${APP_VERSION}', 'commit': '${GIT_COMMIT}', 'build_date': '${BUILD_DATE}', 'source_url': 'https://github.com/TheLastFrame/TiPTiB', 'releases_url': 'https://github.com/TheLastFrame/TiPTiB/releases'}; Path('app/VERSION.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')"

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
