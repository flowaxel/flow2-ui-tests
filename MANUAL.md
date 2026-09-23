# flow2-ui-tests — Manual

A standalone Playwright/pytest test suite that checks whether a flow2
installation's basic functions actually work, driven from a real
headless browser against any flow2 URL you give it. This document is
the full how-to; see [`README.md`](README.md) for the shorter overview
and the reasoning behind each design choice (why it's a separate image
from the Ubuntu 26 port, why nothing asserts on custom metadata field
names, etc.).

## 1. What this is for

Every fix in this tool's own git history started the same way: someone
clicked through flow2 by hand, found something broken (a picture
showing "picture not found" on click-through, a picture showing up
under a "videos only" search), and only then tracked down the real
cause. This suite exists so that class of regression gets caught by
running a command, not by a person clicking through the app again.

It is **not** a replacement for testing your own custom features,
metadata fields, or business logic - see [`README.md`](README.md)'s
"Design constraint" section for why it deliberately can't be. It's a
baseline: does login work, does the dashboard render, does a clip's
picture/video actually load, does editing metadata actually save, does
an upload actually get processed end to end.

## 2. Requirements

- Docker, on whatever machine you run the tests from (does not need to
  be the same machine flow2 is installed on - it just needs network
  access to the flow2 URL).
- A flow2 URL, reachable from wherever you run the container, ending
  in `/flow2/` (the exact URL a browser would open).
- Credentials for a real user on that install with at least upload
  permission (needed for `test_upload.py`; every other test module
  only needs a login).

Nothing else - the image is self-contained (Python, Playwright,
Chromium, the tests and their fixture files all bundled).

## 3. Building the image

```bash
git clone https://github.com/flowaxel/flow2-ui-tests.git
cd flow2-ui-tests
docker build -t flow2-ui-tests .
```

Rebuild whenever you pull new commits - the image bakes the test files
and fixtures in at build time, it doesn't read them from a mounted
volume.

## 4. Running from the command line

```bash
docker run --rm \
  -e FLOW2_URL="https://your-flow2-host/flow2/" \
  -e FLOW2_USER="admin" \
  -e FLOW2_PASSWORD="your-password" \
  flow2-ui-tests
```

This runs every test module and prints a normal `pytest -v` report:
one line per test, then a summary. A clean run looks like:

```
test_login.py::test_login_page_loads PASSED
test_login.py::test_websocket_connects PASSED
...
======================== 14 passed in 62.34s ========================
```

Exit code is `0` if everything passed (or was cleanly skipped), and
non-zero otherwise - safe to use as a CI gate.

### 4.1 Running only some tests

Any extra arguments after the image name go straight to `pytest`:

```bash
# just the login/dashboard checks, verbose
docker run --rm -e FLOW2_URL=... -e FLOW2_USER=... -e FLOW2_PASSWORD=... \
  flow2-ui-tests -k "login or dashboard" -v

# just one file
docker run --rm -e FLOW2_URL=... -e FLOW2_USER=... -e FLOW2_PASSWORD=... \
  flow2-ui-tests test_clipdetails.py
```

### 4.2 Environment variables

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `FLOW2_URL` | yes | - | Base URL flow2 is served from, including the trailing `/flow2/`. |
| `FLOW2_USER` | yes | - | Username to log in with. |
| `FLOW2_PASSWORD` | yes | - | Password for that user. |
| `FLOW2_INSECURE_TLS` | no | `1` | `1` tolerates a self-signed/untrusted TLS certificate (typical for test/dev instances). Set to `0` to require a valid chain. |
| `FLOW2_TEST_UPLOAD` | no | `1` | Set to `0` to skip `test_upload.py` entirely - useful if the test user has no upload permission, or to skip the slowest part of the suite for a quick check. |
| `FLOW2_UPLOAD_TIMEOUT` | no | `180` | Seconds to wait for an uploaded test file to finish automatic ingest/preview processing before the upload tests fail. Raise this if the target install's transcode pipeline is slow or queued. |
| `FLOW2_WEBUI` | no | `0` | Set to `1` to start the web GUI (section 5) instead of running pytest directly - equivalent to passing `--webui`. |

## 5. Running the web GUI

For a tester who'd rather use a form than set environment variables:

```bash
docker run --rm -p 8899:8899 flow2-ui-tests --webui
```

Then open `http://localhost:8899` (or whatever host/port you mapped
`8899` to). The page has:

- **flow2 URL / Username / Password** - same meaning as the env vars
  above.
- **Allow self-signed / untrusted TLS certificate** - checked by
  default; uncheck it to require a valid cert chain.
- **Upload ingest timeout** - same as `FLOW2_UPLOAD_TIMEOUT`.
- **Which tests to run** - a checklist of the five test modules
  (section 6); uncheck "Upload / ingest / preview" for a faster run
  that skips the slowest part.

Clicking "Run tests" starts the run in the background and takes you to
a results page that refreshes itself every couple of seconds while the
run is in progress, then settles on a green "passed" or red "failed"
badge with the full `pytest` output underneath. Use "&larr; new run"
to go back and run again with different settings.

**This mode has no login or access control of its own.** Anyone who
can reach port `8899` can open the form, and the form briefly holds
the flow2 password you type into it in the container's memory for the
duration of the run. Treat it like any other local dev tool: run it on
your own machine or a trusted internal network, don't put it behind a
public URL, and don't leave the container running longer than you're
actively using it.

## 6. What each test module checks

- **`test_login.py`** - the login page loads with a username/password
  field; the frontend's WebSocket connection to the backend comes up
  (the password field only enables once it does - a real, historical
  bug broke exactly this); valid credentials log in; a wrong password
  is rejected (the login form stays up, doesn't just silently fail).
- **`test_dashboard.py`** - the logged-in shell renders without a
  leaked backend error or a JS console error; every thumbnail image
  already visible on the dashboard actually loads (this is the general
  form of the "broken image" bug class this suite exists to catch).
- **`test_search.py`** - the top search bar runs a fulltext search
  without error; the file-type filter icons (image/video/document/
  audio) actually narrow results, and - more precisely - a "videos
  only" search never returns a clip whose own `media` field doesn't
  contain "video" (and likewise for pictures). This is a direct
  regression test for a bug where an unmapped search field silently
  dropped the entire filter and returned everything, unfiltered.
- **`test_clipdetails.py`** - opens an existing clip's detail page (a
  real double-click on its thumbnail, matching how a person actually
  navigates there - a single click only selects it) and checks the
  main image or video player actually renders. Then edits the clip's
  title, saves, and re-fetches the clip from the server (not just the
  page's own state) to confirm the edit actually persisted - and
  restores the original title afterward either way.
- **`test_upload.py`** (skippable via `FLOW2_TEST_UPLOAD=0`) - uploads
  a small real picture and a small real video (bundled in
  `fixtures/`), waits for the install's own automatic ingest/preview
  pipeline to pick each one up (this can take a while depending on the
  install's transcode setup - see `FLOW2_UPLOAD_TIMEOUT`), then checks
  each one's thumbnail and full media view both actually load. This is
  the most complete end-to-end check: upload -> backend processing ->
  something a user can actually see.

## 7. Reading a failure

Every assertion message in this suite is written to say what's
actually wrong and, where the cause is a known bug class, points at
the git commit that fixed it in the original install this suite was
built against - e.g. "the filter is not actually being applied
server-side (likely an unmapped custom 'media' search field in the
install's soapapidef, see this module's docstring)". Start there before
re-running - the message is usually enough to know what to check on
the flow2/backend side.

If a test module fails to even *start* (an error before any test
result line), check:

- `FLOW2_URL` actually ends in `/flow2/` and is reachable from inside
  the container (`docker run --rm flow2-ui-tests curl ...`-style
  checks aren't built in, but a plain `docker run --rm --entrypoint
  curl flow2-ui-tests -v <url>` works for a quick reachability check).
- The target's TLS certificate - if it's self-signed and
  `FLOW2_INSECURE_TLS` got set to `0` somehow, every request fails at
  the TLS handshake before flow2 is ever involved.
- Credentials are actually valid by logging into that same URL in a
  real browser first.

## 8. Extending the suite

Add a new `test_*.py` module for anything not covered by section 6.
The one rule that matters (see `README.md`'s "Design constraint"
section): never assert on a specific custom metadata field name,
value, or exact count of pre-existing library content - every
installation configures its own `custom_metadata_def`, and a test that
assumes one install's schema will just fail against every other
install for no real reason. Assert on structure and behavior instead
(does *something* load, does a change actually persist, is a filtered
result set a real subset of the unfiltered one) - see any existing
test module for the pattern.
