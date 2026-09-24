# flow2-ui-tests

A standalone, portable UI smoke-test suite for **flow2** (FlowCenter's
Node.js/React middleware+GUI), driven by Playwright against a real
browser. Deliberately **not** tied to this repo's Ubuntu 26 port or to
any one FlowCenter installation - point it at any flow2 instance
(this test deployment, a production install, an old one on another
host) via environment variables, and it builds and runs as its own
Docker image, independent of `ubuntu26/Dockerfile.build`.

See [`MANUAL.md`](MANUAL.md) for the full how-to (building, every
environment variable, the web GUI, what each test checks, reading a
failure, extending the suite). This file stays short - the reasoning
behind the design choices.

## Why a separate image

`ubuntu26/ui-tests/` (see its own `test_basic.py`) tests the *legacy*
CGI-XML GUI (`/mfc/*.cgi`) and lives inside the Ubuntu 26 port's own
build container, because it only makes sense against a backend built
from this repo's source. flow2 is a separate product surface that any
FlowCenter installation - this one or a decades-older one on a
different host - can run in front of its own backend. Packaging its
tests as their own image means:

- you can test an installation you didn't build or deploy yourself,
  including ones this repo has nothing to do with;
- a broken/incompatible Ubuntu 26 build never blocks running these
  tests against a known-good instance elsewhere, and vice versa;
- the image only needs a URL and credentials, nothing else about the
  target's environment.

## Design constraint: metadata is not fixed

Every FlowCenter installation configures its own custom metadata
fields via a SOAP API definition XML (`soapapidef/*.xml` -
`custom_metadata_def` in flow2's `config.json`), and different
installs map completely different field names to completely different
`spots` columns (see this repo's own
`Flowcenter_install/stylesheets/mfccgi/soapapidef/flowdemo.xml` for
one example, which is itself just a stand-in for a real customer's
config). **These tests never assert on a specific custom metadata
field name, value, or count of pre-existing clips.** Everything here
checks structural/behavioral invariants that hold for any install:

- login succeeds/fails correctly, the WebSocket connects;
- the dashboard and a fulltext search render without a leaked backend
  error or a JS exception;
- an uploaded file eventually becomes visible and viewable (its
  thumbnail and, when opened, its full media each load as a real
  image/video - not a broken image, not "picture not found"), without
  checking *what* metadata got attached to it;
- toggling a file-type filter (image/video/document/audio) never
  *increases* the result count versus no filter, and a type-only
  filter's results are internally consistent (see `test_search.py`
  for the exact invariant) - without hardcoding what's actually in the
  library.

If a target install doesn't support a given feature at all (no
upload permission for the test user, no transcoding pipeline
configured), the corresponding test is designed to skip with a clear
reason rather than fail - see each test module's own docstring.

## Usage

```bash
docker build -t flow2-ui-tests .

docker run --rm \
  -e FLOW2_URL="https://transcoder1.flowcenter.de:2026/flow2/" \
  -e FLOW2_USER="admin" \
  -e FLOW2_PASSWORD="TestFlow2026!" \
  flow2-ui-tests
```

Optional environment variables:

| Variable                    | Default | Meaning                                                                                          |
|------------------------------|---------|---------------------------------------------------------------------------------------------------|
| `FLOW2_URL`                  | (required) | Base URL flow2 is served from, including the `/flow2/` path prefix.                            |
| `FLOW2_USER` / `FLOW2_PASSWORD` | (required) | Credentials for a real user on the target install.                                          |
| `FLOW2_INSECURE_TLS`         | `1`     | Set to `0` to require a valid TLS chain (default tolerates self-signed certs, common in test/dev). |
| `FLOW2_TEST_UPLOAD`          | `1`     | Set to `0` to skip the upload/ingest/view round-trip tests (`test_upload.py`) entirely.          |
| `FLOW2_UPLOAD_TIMEOUT`       | `180`   | Seconds to wait for an uploaded file to finish automatic ingest/preview processing before failing. Installs with a slower/queued transcode pipeline may need this raised. |
| `FLOW2_TEST_PERMISSIONS`     | `1`     | Set to `0` to skip the admin-vs-restricted-user rights matrix (`test_permissions.py`) entirely.  |
| `FLOW2_LOWPRIV_USER` / `FLOW2_LOWPRIV_PASSWORD` | `flow2uitest_lowpriv` / `TestLowpriv2026!` | Credentials for the restricted account `test_permissions.py` creates (if missing) and logs into. Point at an existing low-privilege account instead if you'd rather not let the suite create one. |
| `FLOW2_LOWPRIV_LEVEL_LABEL`  | `Level 1` | The exact option text to pick in the admin "Neuer Benutzer" form's Userlevel dropdown when creating the restricted account. |
| `FLOW2_TEST_PROJECT_NAME` / `FLOW2_TEST_ROOM_NAME` | `flow2uitest_project` / `flow2uitest_room` | Name given to the project/room `test_projects.py`/`test_rooms.py` create each run. |

Pass extra `pytest` arguments after the image name, e.g.
`docker run --rm -e ... flow2-ui-tests -k test_login -v`.

## Web GUI

For a tester who'd rather fill in a form than set environment
variables and read a raw log: `--webui` (or `-e FLOW2_WEBUI=1`) starts
a small Flask app instead of running pytest directly. It's the exact
same test suite underneath - the form just collects the same
URL/credentials/options the CLI takes as env vars, and the results
page shows the same `pytest -v` output, live, while the run is in
progress.

```bash
docker run --rm -p 8899:8899 flow2-ui-tests --webui
# open http://localhost:8899
```

The form: flow2 URL, username, password, a TLS-trust checkbox, the
upload timeout, and a checklist of which test modules to run (so a
quick check doesn't have to wait for the slower upload round trip).
Submitting starts the run in a background thread and redirects to a
status page that auto-refreshes every 2s until it's done, then shows
pass/fail and the full output.

**No authentication of its own** - anyone who can reach the container's
`8899` reaches the form, and it accepts and briefly holds the flow2
password it's given to run pytest with. Don't publish this port openly;
run it on a trusted network/loopback, same as you would a local dev
tool, not something you'd put behind a public URL as-is.

## What's covered right now

- `test_login.py` - login page loads, valid credentials succeed, wrong
  password is rejected, the app's WebSocket API connects.
- `test_dashboard.py` - the logged-in shell loads without a leaked
  backend error or console error; every thumbnail image already
  visible on the dashboard actually loads (no broken images).
- `test_search.py` - a fulltext search runs and returns without error;
  the file-type filter icons behave consistently with an unfiltered
  search (see the module docstring for the exact invariant checked).
- `test_upload.py` - uploads a small real picture and a small real
  video (`fixtures/`), waits for the install's own ingest/preview
  pipeline to pick them up, then verifies each one's thumbnail and
  full-media view both actually load - this is the exact class of bug
  ("picture not found" on click-through, a picture showing up under a
  video-only search) that motivated writing this suite in the first
  place; see this repo's git log around `65aef3f` / `22d6f9c` for the
  two real installation bugs it would have caught immediately instead
  of needing a manual, from-scratch investigation.
- `test_clipdetails.py` - opens an existing clip's detail page
  (`/clipdetails/<id>`, via a real double-click on its thumbnail - a
  single click only selects it, see the module/`open_clip_details()`
  docstrings for why that distinction matters for automation) and
  checks its main image/video actually renders - this is a *third*,
  separately-discovered instance of the "picture not found" bug class,
  in a code path that builds its own thumbnail URL by hand instead of
  calling `mediafile.getUrl()` (see commit `a802775`). It also drives
  a full metadata edit-and-save round trip (enter edit mode, change
  the title, save, then re-fetch the clip fresh from the API to
  confirm the change actually persisted server-side rather than just
  changing in the DOM) and restores the original value afterward.

- `test_navigation.py` - Settings/Einstellungen, Administration,
  Projects, Rooms and logout all load (or, for logout, actually return
  to the login screen) without a leaked backend error or console
  error. Deliberately shallow, one step up from test_dashboard.py -
  broad coverage of flow2's other main pages every install has, not a
  deep check of any one of them.
- `test_permissions.py` - an admin-vs-restricted-user rights matrix:
  creates a second, low-privilege account on demand and compares actual
  rendered UI between it and the admin account, rather than trusting
  the granting config in isolation - a restricted account seeing the
  Administration link, or seeing the same number of delete controls on
  a clip detail page as admin, means granting isn't actually
  restricting anything regardless of what the config says it should.
  Found a real gap this way on the reference install: a Level 1 account
  gets full, unrestricted access to every Administration tab (Benutzer,
  System-Einstellungen, ...) - only `deleteclip` is actually enforced,
  both in the granting config and in what's rendered.
- `test_projects.py` / `test_rooms.py` - create a real project/room and
  check its detail page shows it correctly. No edit-round-trip test for
  either: reading this install's own bundled React source
  (`Flow2/pages/Projects/ProjectView.js`, `Flow2/pages/Rooms/RoomView.js`)
  shows both "details" panels are built entirely out of plain read-only
  `<p>` text - no input field, no pencil/save icon, no edit menu entry
  anywhere in that render path, confirmed against the live UI too.
  Room *creation* itself has a real, separate bug worth testing
  directly, though: the popup's "title" field is sent to the backend
  correctly (confirmed via the WebSocket frame), but the backend's own
  response for the newly created room comes back with `title`, `owner`,
  `roomtype` and nearly every other metadata field literally set to the
  string `"notset"` - not the submitted value, not empty either. Both
  fixtures create a fresh project/room every run rather than reusing one
  by name (this install's own project-tree/room-tree text isn't a
  reliable enough handle to find a specific one back safely - see
  `ensure_test_project`'s docstring in conftest.py), so repeated runs
  will accumulate test projects/rooms on the target install over time.

## Performance timings

Every run measures and reports how long the operations that matter
most for comparing backend/middleware performance across installs
actually took: login/WS connect, dashboard load, a search, opening a
clip, a metadata save round trip, and (usually the real bottleneck)
upload -> ingest -> visible. A table prints at the end of every run
(min/avg/max per operation), and the full, raw measurements are
written to `/tests/perf-report.json` inside the container (mount a
volume there, or override the path with `FLOW2_PERF_REPORT`, to keep
results outside the container for comparing across installs/runs).
See `perf.py`.

## What's not covered yet

Projects/rooms detail pages (only that they load), distribution/
download links, admin sub-pages beyond "does Administration load",
permission/granting edge cases, NVENC-specific transcode verification.
Extend by adding a new `test_*.py` module following the same
schema-agnostic rule above.

## A note on reliability against a long-lived test instance

`test_upload.py` and `test_clipdetails.py` were, at points while
building this suite, observed to fail intermittently against a single
flow2 instance that had already been through many hours of manual
testing, redeploys, and repeated logins the same day - a WebSocket
call failing with a generic "[object Object]"/"login failed" error
from felib.js, even though the underlying operation (checked directly
against the database) had actually succeeded. `wait_until()` now
tolerates and retries through exactly this, and upload tests get their
own throwaway login session rather than the shared one other tests
reuse (see conftest.py's docstrings for both), but this class of
flakiness wasn't fully root-caused - it may be specific to a backend/
session that's been kept alive and repeatedly re-authenticated against
for a long time, rather than something every run against a normal,
freshly-deployed install will hit. If a run against a fresh install is
flaky in this exact way, that's worth a real bug report, not just a
retry.
