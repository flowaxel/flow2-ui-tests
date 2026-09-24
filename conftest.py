"""
Shared fixtures for the flow2 UI smoke tests.

Everything here is configured purely from environment variables - see
README.md - so the exact same image/tests run against any flow2
installation. Nothing in this file (or any test module) may assume a
particular custom metadata schema; see README.md's "Design constraint"
section for why.
"""
import os
import re
import time
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import perf
from perf import timed

FLOW2_URL = os.environ["FLOW2_URL"].rstrip("/") + "/"
FLOW2_USER = os.environ["FLOW2_USER"]
FLOW2_PASSWORD = os.environ["FLOW2_PASSWORD"]
INSECURE_TLS = os.environ.get("FLOW2_INSECURE_TLS", "1") != "0"
UPLOAD_TIMEOUT = int(os.environ.get("FLOW2_UPLOAD_TIMEOUT", "180"))
TEST_UPLOAD = os.environ.get("FLOW2_TEST_UPLOAD", "1") != "0"

# A restricted second account for test_permissions.py's admin-vs-restricted
# comparisons. Created on demand (see `ensure_lowpriv_user`) rather than
# requiring the operator to pre-provision one - the fixed username makes
# that idempotent across runs. Override via env if a real install already
# has a suitable low-privilege account to reuse instead.
LOWPRIV_USER = os.environ.get("FLOW2_LOWPRIV_USER", "flow2uitest_lowpriv")
LOWPRIV_PASSWORD = os.environ.get("FLOW2_LOWPRIV_PASSWORD", "TestLowpriv2026!")
LOWPRIV_LEVEL_LABEL = os.environ.get("FLOW2_LOWPRIV_LEVEL_LABEL", "Level 1")
TEST_PERMISSIONS = os.environ.get("FLOW2_TEST_PERMISSIONS", "1") != "0"

# strings that show up when a CGI/SOAP call crashes, a C++ exception
# escapes, or a SQL error leaks into a JSON/HTML response - if any of
# these show up somewhere we weren't specifically provoking a failure,
# something is broken. Deliberately backend-error-shaped, not
# frontend-specific, since flow2's own error boundary text varies by
# locale and isn't something every install necessarily configures the
# same way.
ERROR_MARKERS = [
    "Query error",
    "terminate called after throwing",
    "Internal Server Error",
    "Premature end of script headers",
    "core dumped",
    "SOAP-ENV:Fault",
]


def assert_no_leaked_error(text):
    for marker in ERROR_MARKERS:
        assert marker not in text, f"page/response leaked a backend error marker: {marker!r}"


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(ignore_https_errors=INSECURE_TLS)
    console_errors = []
    pg = context.new_page()
    # flow2 is a React SPA - a JS exception during render often leaves
    # the DOM looking merely "empty" rather than throwing anything
    # Playwright would surface on its own, so console errors are the
    # only reliable signal something broke client-side.
    pg.on("console", lambda msg: console_errors.append(msg.text()) if msg.type == "error" else None)
    pg.console_errors = console_errors
    yield pg
    context.close()


@pytest.fixture
def fresh_logged_in_page(page):
    """
    A freshly logged-in page in its OWN browser context, not the
    shared session `logged_in_page` gives every other test.

    Upload specifically has been observed to leave the *shared*
    session's WebSocket unable to make further API calls afterward
    (every subsequent window.flow call failing with a backend "Error:
    [object Object]"/login-shaped error) - flow2's own upload handling
    does its own separate internal login (config.json's
    middleware.granting.fclogin, a fixed non-human account, not the
    test user) alongside the interactive session's, and something
    about that interaction breaks the shared session's own state in a
    way this suite couldn't isolate further without flow2's own
    source. Giving upload tests a throwaway session avoids destabilizing
    every other test that runs after them, at the cost of one extra
    login (see conftest.py's `_shared_session` for why that's
    normally avoided) - worth it here specifically.
    """
    with timed("page_load_to_interactive"):
        page.goto(FLOW2_URL, wait_until="networkidle", timeout=30000)
    _do_login(page)
    return page


def _find_first(page, selectors, timeout=10000):
    """Try each selector in order, return the first that matches at least one element."""
    last_err = None
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except PlaywrightTimeoutError as e:
            last_err = e
    raise last_err


def _do_login(page):
    """
    Drives the login form on an already-navigated-to page. flow2's
    login form only enables its password field once the frontend's
    WebSocket connection to the backend is up (see this repo's own
    felib.js getSocket()/WebSocket.OPEN history for a real bug that
    broke exactly this) - waiting for that is itself already an
    implicit check that the WS transport works, not just HTTP.

    Selectors deliberately try flow2's default English placeholder
    text first (stable across installs that don't localize the login
    screen) and fall back to input[type=password]/the first
    text-like input in the form, since some installs may run flow2 in
    a different locale.
    """
    password_field = _find_first(page, [
        'input[placeholder="Password" i]',
        'input[type="password"]',
    ])
    with timed("websocket_connect"):
        page.wait_for_function(
            "el => !el.disabled",
            arg=password_field.element_handle(),
            timeout=20000,
        )

    username_field = _find_first(page, [
        'input[placeholder="Username" i]',
        'input[type="text"]:visible, input[type="email"]:visible',
    ])

    username_field.click()
    username_field.type(FLOW2_USER, delay=20)
    password_field.click()
    password_field.type(FLOW2_PASSWORD, delay=20)

    login_button = _find_first(page, [
        'button:has-text("Log in")',
        'button:has-text("Login")',
        'button:has-text("Anmelden")',
        'button[type="submit"]',
    ])
    with timed("login_submit_to_authenticated"):
        login_button.click(force=True)

        # no single stable "you are logged in" DOM marker is guaranteed
        # across custom UI configs, so wait for the password field to
        # disappear (the login form unmounts on success) instead of
        # asserting on any specific post-login content.
        password_field.wait_for(state="detached", timeout=20000)
        page.wait_for_timeout(1000)


@pytest.fixture(scope="session")
def _shared_session(browser):
    """
    One flow2 login, shared by every test that needs to already be
    logged in, instead of a fresh login per test function.

    This isn't just a speed optimization (logging in ~15+ times added
    up to a real chunk of a run, visible in the perf report's own
    login_submit_to_authenticated numbers) - it fixes a genuine test
    bug found by running the full suite together: many FlowCenter
    installs only allow a user to be logged in once at a time, so a
    second `logged_in_page` fixture logging the SAME test user in
    again mid-run silently invalidated the first session's WebSocket,
    surfacing as an unrelated "Error: login failed" deep inside
    felib.js on whichever test happened to run next. One shared
    session for the whole suite avoids the collision entirely (see
    also README's suggestion to use a dedicated, non-human test user
    for exactly this kind of reason).

    Tests that specifically exercise the login *form* itself
    (test_login.py) intentionally do NOT use this fixture - they need
    a fresh, unauthenticated page each time, which the plain `page`
    fixture already provides.
    """
    context = browser.new_context(ignore_https_errors=INSECURE_TLS)
    console_errors = []
    pg = context.new_page()
    pg.on("console", lambda msg: console_errors.append(msg.text()) if msg.type == "error" else None)
    pg.console_errors = console_errors

    with timed("page_load_to_interactive"):
        pg.goto(FLOW2_URL, wait_until="networkidle", timeout=30000)
    _do_login(pg)

    yield pg
    context.close()


@pytest.fixture
def logged_in_page(_shared_session):
    """
    The shared, already-authenticated session (see `_shared_session`),
    reset to a known-good starting point for each test: a fresh
    console-error list (so one test's warnings don't fail the next
    one's assertion) and back at the app's root route (in case a
    previous test navigated elsewhere), without a second login.
    """
    _shared_session.console_errors.clear()
    # NOT page.goto() - a hard navigation reloads the whole page, which
    # tears down the in-memory WebSocket/login state a real page.goto()
    # doesn't automatically restore, surfacing as a confusing backend
    # "Unable to get logindata for user"/"login failed" error on the
    # NEXT test rather than a clean re-login (found by that exact
    # failure appearing only after adding this reset). Client-side
    # History API navigation + a manual popstate event, the same
    # mechanism React Router's own <Link> clicks use, gets back to the
    # app's root route without disturbing the live session at all.
    home_path = urlparse(FLOW2_URL).path or "/"
    _shared_session.evaluate(
        """(path) => {
            window.history.pushState({}, '', path);
            window.dispatchEvent(new PopStateEvent('popstate'));
        }""",
        home_path,
    )
    _shared_session.wait_for_timeout(1000)

    # The shared WS session has been observed to drop on its own after
    # a long-running test (a 15-field metadata edit/save loop, in
    # particular) even without any reload - some install-side idle/
    # session timeout, not something this suite controls. Detected by
    # a lightweight window.flow call rather than assumed still-good;
    # re-login transparently rather than let it surface as a confusing
    # "Unable to get logindata for user" deep inside felib.js on
    # whatever test happens to run next.
    session_alive = _shared_session.evaluate(
        """async () => {
            try { await window.flow.getClipsByFulltext('', { limit: 1 }); return true; }
            catch (e) { return false; }
        }"""
    )
    if not session_alive:
        _shared_session.goto(FLOW2_URL, wait_until="networkidle", timeout=30000)
        _do_login(_shared_session)

    return _shared_session


def _open_user_menu(page):
    page.click(f"text={FLOW2_USER}", force=True, timeout=5000)
    page.wait_for_timeout(400)


def _navigate_to_admin_users(page):
    """Drives Administration > Benutzer from the top-level nav, returns True on success."""
    _open_user_menu(page)
    admin_link = page.locator('a:has-text("Administration")').first
    if admin_link.count() == 0:
        return False
    admin_link.click()
    page.wait_for_timeout(1500)
    try:
        users_tab = _find_first(page, ['text=Benutzer', 'text=Users'], timeout=3000)
    except PlaywrightTimeoutError:
        return False
    users_tab.click(force=True)
    page.wait_for_timeout(1500)
    return True


def _create_user_if_missing(page, username, password, level_label, first_name, last_name):
    """
    Creates `username` via Administration > Benutzer > Neuer Benutzer if it
    doesn't already exist in the user list. Idempotent (safe to call every
    run) and returns True if the account exists afterward (whether it was
    just created or already there), False if it could not be created.

    Scopes the new-user form's inputs to the panel actually containing the
    "Speichern" button, rather than the whole page: the page also has
    several unrelated search-box inputs (top search bar, project/room
    sidebar filters) that a plain `page.locator('input')` would also match,
    found the same way editable_metadata_fields() had to filter down to the
    clip metadata panel specifically.
    """
    if not _navigate_to_admin_users(page):
        return False
    if username in page.content():
        return True

    try:
        new_user_btn = _find_first(page, ['text=Neuer Benutzer', 'text=New User'], timeout=3000)
    except PlaywrightTimeoutError:
        return False
    new_user_btn.click(force=True)
    page.wait_for_timeout(1000)

    found = page.evaluate(
        """() => {
            const saveBtn = Array.from(document.querySelectorAll('*')).find(
                el => el.children.length === 0 && el.innerText &&
                (el.innerText.trim() === 'Speichern' || el.innerText.trim() === 'Save')
            );
            let panel = saveBtn;
            for (let hop = 0; hop < 8 && panel; hop++) {
                if (panel.querySelectorAll('input, select').length >= 5) break;
                panel = panel.parentElement;
            }
            if (!panel) return false;
            panel.setAttribute('data-newuser-panel', '1');
            return true;
        }"""
    )
    if not found:
        return False

    panel = page.locator('[data-newuser-panel="1"]')
    fields = panel.locator('input, select')
    # order matches the real form: Benutzername, E-Mail, Userlevel,
    # Passwort, Vorname, Nachname (no stable name/id attributes to select
    # by - confirmed by inspecting the live form, not guessed)
    fields.nth(0).fill(username)
    fields.nth(1).fill(f"{username}@example.invalid")
    fields.nth(2).select_option(label=level_label)
    fields.nth(3).fill(password)
    fields.nth(4).fill(first_name)
    fields.nth(5).fill(last_name)

    _find_first(page, ['text=Speichern', 'text=Save'], timeout=3000).click(force=True)
    page.wait_for_timeout(2000)

    return _navigate_to_admin_users(page) and username in page.content()


@pytest.fixture(scope="session")
def ensure_lowpriv_user(_shared_session):
    """
    Creates the LOWPRIV_USER account once per test run (via the admin
    session), if it doesn't already exist. Skips every dependent test
    (rather than failing) if it can't be created - either this install's
    admin has no Administration access at all, or is missing the
    `fc_edituser` server-wide grant (found for real on the install this was
    built against: even the level6 admin account lacked it by default,
    with no install-time step that sets it - see this repo's own commit
    history/PR description for the exact backend SOAP call that fixes it,
    since there's no button for it in the UI itself).
    """
    if not TEST_PERMISSIONS:
        pytest.skip("FLOW2_TEST_PERMISSIONS=0")
    # This fixture is session-scoped so it can't depend on `logged_in_page`
    # (function-scoped) for its usual reset-to-home - do the same
    # client-side navigation directly, since whatever test happened to run
    # right before this fixture first executes may have left the shared
    # session on some other route (e.g. still on /admin), where the
    # top-nav user menu isn't necessarily rendered the same way.
    home_path = urlparse(FLOW2_URL).path or "/"
    _shared_session.evaluate(
        """(path) => {
            window.history.pushState({}, '', path);
            window.dispatchEvent(new PopStateEvent('popstate'));
        }""",
        home_path,
    )
    _shared_session.wait_for_timeout(1000)
    ok = _create_user_if_missing(
        _shared_session, LOWPRIV_USER, LOWPRIV_PASSWORD, LOWPRIV_LEVEL_LABEL,
        "Flow2UiTest", "Lowpriv",
    )
    if not ok:
        pytest.skip(
            f"could not create/find the '{LOWPRIV_USER}' test account - the admin "
            "user either has no Administration access, or is missing the backend "
            "fc_edituser grant (a server-wide flow2 permission, not role-specific; "
            "no UI to set it, needs a real edituseroptions SOAP call)"
        )
    return LOWPRIV_USER


@pytest.fixture(scope="session")
def _lowpriv_session(browser, ensure_lowpriv_user):
    """The restricted account's own session, separate from the admin one."""
    context = browser.new_context(ignore_https_errors=INSECURE_TLS)
    console_errors = []
    pg = context.new_page()
    pg.on("console", lambda msg: console_errors.append(msg.text()) if msg.type == "error" else None)
    pg.console_errors = console_errors

    pg.goto(FLOW2_URL, wait_until="networkidle", timeout=30000)
    password_field = _find_first(pg, ['input[placeholder="Password" i]', 'input[type="password"]'])
    pg.wait_for_function("el => !el.disabled", arg=password_field.element_handle(), timeout=20000)
    username_field = _find_first(pg, ['input[placeholder="Username" i]', 'input[type="text"]:visible'])
    username_field.click()
    username_field.type(LOWPRIV_USER, delay=20)
    password_field.click()
    password_field.type(LOWPRIV_PASSWORD, delay=20)
    login_button = _find_first(pg, [
        'button:has-text("Log in")', 'button:has-text("Login")',
        'button:has-text("Anmelden")', 'button[type="submit"]',
    ])
    login_button.click(force=True)
    password_field.wait_for(state="detached", timeout=20000)
    pg.wait_for_timeout(1000)

    yield pg
    context.close()


@pytest.fixture
def lowpriv_logged_in_page(_lowpriv_session):
    """Same reset-to-home pattern as `logged_in_page`, for the restricted account."""
    _lowpriv_session.console_errors.clear()
    home_path = urlparse(FLOW2_URL).path or "/"
    _lowpriv_session.evaluate(
        """(path) => {
            window.history.pushState({}, '', path);
            window.dispatchEvent(new PopStateEvent('popstate'));
        }""",
        home_path,
    )
    _lowpriv_session.wait_for_timeout(1000)
    return _lowpriv_session


@pytest.fixture
def picture_fixture_path():
    return os.path.join(os.path.dirname(__file__), "fixtures", "test_picture.png")


@pytest.fixture
def video_fixture_path():
    return os.path.join(os.path.dirname(__file__), "fixtures", "test_video.mp4")


def wait_until(fn, timeout, interval=3, description="condition"):
    """
    Poll fn() until it returns a truthy value or timeout (seconds)
    elapses. Always records how long it actually took under perf - the
    slow ones here (upload -> ingest -> visible, above all) are
    exactly the backend/middleware performance numbers worth comparing
    across installs, per Axel's own reason for adding this module.

    Tolerates fn() raising, rather than letting one bad poll kill the
    whole wait: a WebSocket call made *while* the backend is mid-way
    through processing what we're polling for (a fresh upload, a
    reconnect after one) can throw a transient error that has nothing
    to do with whether the condition is actually met - observed for
    real as an intermittent "[object Object]" from felib.js on a
    getClipsByFulltext call placed seconds after a successful upload
    that had, per the database, already succeeded. Only the last
    `timeout` seconds worth of exceptions are swallowed; one still
    surfaces (via the final AssertionError's cause) if the condition
    never gets met at all.
    """
    start = time.monotonic()
    deadline = start + timeout
    last_result = None
    last_exc = None
    while time.monotonic() < deadline:
        try:
            last_result = fn()
        except Exception as e:
            last_exc = e
            last_result = None
        if last_result:
            perf.record(f"wait_until: {description}", time.monotonic() - start, timed_out=False)
            return last_result
        time.sleep(interval)
    perf.record(f"wait_until: {description}", time.monotonic() - start, timed_out=True)
    raise AssertionError(f"timed out after {timeout}s waiting for: {description}") from last_exc


def open_clip_details(page, clip_thumbnail_src_fragment):
    """
    Navigate into a clip's /clipdetails/<id> page by double-clicking its
    thumbnail wherever it's currently rendered (dashboard, search
    results - anywhere Flow2/components/Clip/Clip.js renders one).

    This is a *double*-click deliberately, not a single click: Clip.js
    wires a single click to a selection/highlight callback (for
    multi-select batch actions like add-to-cart) and only a double
    click to actual navigation - a single click, or a dispatched
    'click' MouseEvent, changes nothing about the current route. Found
    by reading Clip.js's own onClick wiring after single clicks
    (including raw dispatched mouse events) reproducibly did nothing.

    `clip_thumbnail_src_fragment` narrows to one specific clip's <img>
    by a substring of its thumbnail.cgi URL (e.g. a filename) - the
    caller decides which clip, this helper only drives the click.
    """
    # A Playwright *locator* click, not a manually-computed
    # getBoundingClientRect()/page.mouse.dblclick() at fixed
    # coordinates - the manual approach doesn't reliably work for a
    # thumbnail sitting near the bottom edge of a "recent items" list
    # once that list has grown past a screenful (a real state reached
    # after enough test uploads over the course of a test day):
    # scrollIntoView({block:'center'}) can't actually center an
    # element that's near the end of the page's total scrollable
    # content, leaving it right at the viewport's bottom edge where a
    # dblclick can silently miss. Playwright's own locator actions
    # scroll and verify actionability themselves before clicking,
    # which is exactly the robustness this needs.
    thumb = page.locator(f'img[src*="thumbnail.cgi"][src*="{clip_thumbnail_src_fragment}"]').first
    thumb.wait_for(state="visible", timeout=10000)
    with timed("clip_details_open", clip=clip_thumbnail_src_fragment):
        thumb.dblclick()
        page.wait_for_url("**/clipdetails/**", timeout=15000)
        page.wait_for_timeout(1500)


def enter_metadata_edit_mode(page):
    """
    Click the pencil icon that turns the clip detail page's read-only
    metadata fields into editable inputs (ClipDetailsToolbar's edit
    toggle). `svg.fa-pen` alone isn't unique - some installs also
    render a second, unrelated fa-pen icon elsewhere on the page (seen
    on one real install: a zero-size, not-actually-visible edit icon
    inside an InfoSection media-file table) - `:visible` is what
    actually disambiguates them, found by comparing bounding boxes of
    every fa-pen on the page after a `.first` click silently activated
    the wrong control.
    """
    page.locator("svg.fa-pen:visible").first.click(force=True)
    page.wait_for_timeout(1000)


def save_metadata_edit(page):
    """Click the save (floppy disk) icon that appears once in edit mode."""
    with timed("metadata_save_roundtrip"):
        page.locator("svg.fa-save:visible").first.click(force=True)
        page.wait_for_timeout(1500)


def editable_metadata_fields(page):
    """
    Every text/textarea input on the clip detail page once in edit
    mode, that's part of the metadata panel rather than the app's own
    search bars - deliberately not selected by a label like "Title"/
    "Titel", because that field doesn't even exist on every install: a
    real second install used for this suite has no title-like field at
    all (its metadata panel is "Event"/"Tape Number"/"Creator"/etc.
    instead) - the whole point of this suite's schema-agnostic design
    (see README), caught only by actually testing against a second,
    differently-configured install.

    Filtered by an empty `placeholder` attribute rather than DOM
    position/ancestry: every metadata field observed across two real,
    differently-skinned installs has placeholder="", while flow2's own
    top search bar and sidebar project/room search boxes (the only
    other plain text inputs normally on this page) always have a
    non-empty one ("Suchbegriff eingeben" etc.) - simpler and more
    robust than trying to identify "the metadata panel" as a specific
    DOM ancestor, which shifted shape between two installs tested here.

    Returns every candidate, plural, rather than just the first: some
    fields in this panel look like ordinary enabled inputs (no
    `readonly`/`disabled` attribute) but are wired to reject or ignore
    typed changes anyway (permission-gated, presumably) - found by a
    `.fill()` on the literal first one silently not sticking. Callers
    should try each in turn and use the first one that actually
    retains a typed value, not just the first one that exists.
    """
    return page.locator(
        'input[type="text"]:visible[placeholder=""], '
        'input[type="text"]:visible:not([placeholder]), '
        "textarea:visible"
    )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """
    Prints every perf.timed() measurement taken during the run as a
    table, and writes the full set to a JSON file (see perf.py) - the
    whole point being a number Axel can diff between installs/runs,
    not just eyeball once in scrollback and forget.
    """
    records = perf.all_records()
    if not records:
        return
    terminalreporter.section("Performance timings")
    for r in records:
        extra = ", ".join(f"{k}={v}" for k, v in r.items() if k not in ("op", "seconds"))
        line = f"{r['op']:<32} {r['seconds']:>8.3f}s"
        if extra:
            line += f"  ({extra})"
        terminalreporter.write_line(line)

    by_op = {}
    for r in records:
        by_op.setdefault(r["op"], []).append(r["seconds"])
    terminalreporter.write_line("")
    terminalreporter.write_line("Per-operation min / avg / max (seconds), across every call this run:")
    for op, values in sorted(by_op.items()):
        terminalreporter.write_line(
            f"  {op:<32} min={min(values):>7.3f}  avg={sum(values) / len(values):>7.3f}  max={max(values):>7.3f}  (n={len(values)})"
        )

    report_path = perf.write_report(FLOW2_URL)
    terminalreporter.write_line(f"\nFull JSON report: {report_path}")
