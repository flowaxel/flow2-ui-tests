"""
A small web GUI wrapped around this same test suite, for a tester who
just wants to point-and-click a flow2 URL/credentials rather than set
environment variables and read a raw pytest log. Runs the exact same
`pytest` this image's CLI entrypoint does - this is a front end for
that, not a second test runner - so anything true of the CLI results
(schema-agnostic assertions, skip behavior, etc., see README.md) is
true here too.

Kept intentionally small: one in-memory job dict (this container has
exactly one tester using it at a time), a form, and a results page
that auto-refreshes while the run is in progress. No database, no
auth beyond whatever network access already reaches this container -
see README.md's "Web GUI" section for the access-control note.
"""
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from html import escape

from flask import Flask, redirect, render_template_string, request, url_for

app = Flask(__name__)

# job_id -> {"status": "running"|"done", "returncode": int|None,
#            "output": str, "started": float, "finished": float|None,
#            "config": dict}
JOBS = {}
JOBS_LOCK = threading.Lock()

TEST_MODULES = [
    ("test_login.py", "Login / WebSocket"),
    ("test_dashboard.py", "Dashboard"),
    ("test_search.py", "Search + type filters"),
    ("test_clipdetails.py", "Clip details + metadata save"),
    ("test_upload.py", "Upload / ingest / preview (slower)"),
]

PAGE_HEAD = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>flow2-ui-tests</title>
<style>
  body { font-family: -apple-system, Segoe UI, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
  h1 { font-size: 1.4rem; }
  label { display: block; margin-top: 1rem; font-weight: 600; font-size: 0.9rem; }
  input[type=text], input[type=password], input[type=number] { width: 100%; box-sizing: border-box; padding: 0.5rem; font-size: 1rem; border: 1px solid #ccc; border-radius: 4px; }
  .checkbox-row { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.75rem; }
  .checkbox-row label { margin-top: 0; font-weight: normal; }
  .modules { margin-top: 0.5rem; }
  .modules label { font-weight: normal; display: flex; align-items: center; gap: 0.5rem; margin-top: 0.4rem; }
  button { margin-top: 1.5rem; padding: 0.7rem 1.4rem; font-size: 1rem; background: #1a1a1a; color: white; border: none; border-radius: 4px; cursor: pointer; }
  button:hover { background: #333; }
  pre { background: #111; color: #ddd; padding: 1rem; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; font-size: 0.85rem; }
  .badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.85rem; font-weight: 600; }
  .running { background: #fff3cd; color: #856404; }
  .passed { background: #d4edda; color: #155724; }
  .failed { background: #f8d7da; color: #721c24; }
  .muted { color: #777; font-size: 0.85rem; }
  a { color: #1a1a1a; }
</style>
</head>
<body>
"""
PAGE_TAIL = "</body></html>"


def _run_pytest_job(job_id, env, pytest_args):
    with JOBS_LOCK:
        JOBS[job_id]["status"] = "running"
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", "-v", *pytest_args],
        cwd=os.path.dirname(__file__),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines = []
    for line in proc.stdout:
        output_lines.append(line)
        with JOBS_LOCK:
            JOBS[job_id]["output"] = "".join(output_lines)
    proc.wait()
    with JOBS_LOCK:
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["returncode"] = proc.returncode
        JOBS[job_id]["finished"] = time.time()


@app.route("/", methods=["GET"])
def index():
    modules_html = "".join(
        f'<label><input type="checkbox" name="modules" value="{mod}" checked> {desc} ({mod})</label>'
        for mod, desc in TEST_MODULES
    )
    body = f"""
    <h1>flow2-ui-tests</h1>
    <p class="muted">Standalone UI smoke tests for any flow2 installation - see README.md
    for what each module actually checks and why nothing here assumes a
    particular custom metadata schema.</p>
    <form method="post" action="{url_for('run')}">
      <label for="url">flow2 URL</label>
      <input type="text" id="url" name="url" placeholder="https://transcoder1.flowcenter.de:2026/flow2/" required>

      <label for="user">Username</label>
      <input type="text" id="user" name="user" required>

      <label for="password">Password</label>
      <input type="password" id="password" name="password" required>

      <div class="checkbox-row">
        <input type="checkbox" id="insecure_tls" name="insecure_tls" checked>
        <label for="insecure_tls">Allow self-signed / untrusted TLS certificate</label>
      </div>

      <div class="checkbox-row">
        <input type="checkbox" id="cleanup" name="cleanup">
        <label for="cleanup">Clean up test data this run creates (projects/rooms/restricted test user) when the run finishes</label>
      </div>

      <label for="upload_timeout">Upload ingest timeout (seconds)</label>
      <input type="number" id="upload_timeout" name="upload_timeout" value="180" min="10">

      <label>Which tests to run</label>
      <div class="modules">{modules_html}</div>

      <button type="submit">Run tests</button>
    </form>
    """
    return PAGE_HEAD + body + PAGE_TAIL


@app.route("/run", methods=["POST"])
def run():
    flow2_url = request.form.get("url", "").strip()
    flow2_user = request.form.get("user", "").strip()
    flow2_password = request.form.get("password", "")
    insecure_tls = "1" if request.form.get("insecure_tls") else "0"
    cleanup = "1" if request.form.get("cleanup") else "0"
    upload_timeout = request.form.get("upload_timeout", "180").strip() or "180"
    selected_modules = request.form.getlist("modules") or [m for m, _ in TEST_MODULES]

    if not flow2_url or not flow2_user or not flow2_password:
        return PAGE_HEAD + "<p>URL, username and password are all required. <a href='/'>Back</a></p>" + PAGE_TAIL, 400

    test_upload = "1" if "test_upload.py" in selected_modules else "0"
    pytest_args = [m for m in selected_modules]

    env = dict(os.environ)
    env.update({
        "FLOW2_URL": flow2_url,
        "FLOW2_USER": flow2_user,
        "FLOW2_PASSWORD": flow2_password,
        "FLOW2_INSECURE_TLS": insecure_tls,
        "FLOW2_TEST_UPLOAD": test_upload,
        "FLOW2_UPLOAD_TIMEOUT": upload_timeout,
        # explicit either way (never left unset): this subprocess has no
        # real terminal for conftest.py's interactive y/N prompt to use,
        # so leaving FLOW2_CLEANUP unset would always silently default
        # to "don't clean up" regardless of what this checkbox says.
        "FLOW2_CLEANUP": cleanup,
    })

    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "starting",
            "returncode": None,
            "output": "",
            "started": time.time(),
            "finished": None,
            "config": {"url": flow2_url, "user": flow2_user, "modules": selected_modules},
        }
    thread = threading.Thread(target=_run_pytest_job, args=(job_id, env, pytest_args), daemon=True)
    thread.start()
    return redirect(url_for("status", job_id=job_id))


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@app.route("/status/<job_id>")
def status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return PAGE_HEAD + f"<p>No such job. <a href='/'>Back</a></p>" + PAGE_TAIL, 404

    output_clean = escape(_ANSI_RE.sub("", job["output"]))
    cfg = job["config"]

    if job["status"] in ("starting", "running"):
        badge = '<span class="badge running">running</span>'
        refresh = '<meta http-equiv="refresh" content="2">'
    else:
        passed = job["returncode"] == 0
        badge = f'<span class="badge {"passed" if passed else "failed"}">{"passed" if passed else "failed"} (exit {job["returncode"]})</span>'
        refresh = ""

    body = f"""
    {refresh}
    <h1>flow2-ui-tests - {escape(cfg['url'])} {badge}</h1>
    <p class="muted">user: {escape(cfg['user'])} · modules: {", ".join(escape(m) for m in cfg['modules'])}</p>
    <p><a href="{url_for('index')}">&larr; new run</a></p>
    <pre>{output_clean or "(starting...)"}</pre>
    """
    return PAGE_HEAD + body + PAGE_TAIL


if __name__ == "__main__":
    port = int(os.environ.get("FLOW2_WEBUI_PORT", "8899"))
    app.run(host="0.0.0.0", port=port)
