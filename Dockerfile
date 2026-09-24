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

COPY conftest.py entrypoint.sh webui.py perf.py ./
COPY test_login.py test_dashboard.py test_search.py test_upload.py test_clipdetails.py test_navigation.py test_permissions.py test_projects.py test_rooms.py ./
COPY fixtures/ ./fixtures/

RUN chmod +x entrypoint.sh

# Only used by `--webui`/FLOW2_WEBUI=1 mode (see entrypoint.sh) - the
# default CLI mode (env vars + pytest) doesn't listen on anything.
EXPOSE 8899

ENTRYPOINT ["./entrypoint.sh"]
