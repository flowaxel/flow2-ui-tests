# flow2-ui-tests

A standalone, portable UI smoke-test suite for **flow2** (FlowCenter's
Node.js/React middleware+GUI), driven by Playwright against a real
browser. Deliberately **not** tied to this repo's Ubuntu 26 port or to
any one FlowCenter installation - point it at any flow2 instance
(this test deployment, a production install, an old one on another
host) via environment variables, and it builds and runs as its own
Docker image, independent of `ubuntu26/Dockerfile.build`.

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

## What's not covered yet

Projects/rooms, distribution/download links, admin pages,
permission/granting edge cases, NVENC-specific transcode verification.
Extend by adding a new `test_*.py` module following the same
schema-agnostic rule above.
