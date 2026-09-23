# Standalone image: Playwright + a real Chromium, nothing else. Not
# based on and not dependent on ubuntu26/Dockerfile.build - see this
# directory's README.md for why. Point it at any flow2 URL via env
# vars at `docker run` time; it doesn't build or know about a
# FlowCenter backend at all.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

WORKDIR /tests

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY conftest.py entrypoint.sh ./
COPY test_login.py test_dashboard.py test_search.py test_upload.py test_clipdetails.py ./
COPY fixtures/ ./fixtures/

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
