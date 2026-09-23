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

import pytest
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

FLOW2_URL = os.environ["FLOW2_URL"].rstrip("/") + "/"
FLOW2_USER = os.environ["FLOW2_USER"]
FLOW2_PASSWORD = os.environ["FLOW2_PASSWORD"]
INSECURE_TLS = os.environ.get("FLOW2_INSECURE_TLS", "1") != "0"
UPLOAD_TIMEOUT = int(os.environ.get("FLOW2_UPLOAD_TIMEOUT", "180"))
TEST_UPLOAD = os.environ.get("FLOW2_TEST_UPLOAD", "1") != "0"

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


@pytest.fixture
def logged_in_page(page):
    """
    A page with a valid flow2 session, landed on the dashboard.

    flow2's login form only enables its password field once the
    frontend's WebSocket connection to the backend is up (see this
    repo's own felib.js getSocket()/WebSocket.OPEN history for a real
    bug that broke exactly this) - waiting for that is itself already
    an implicit check that the WS transport works, not just HTTP.

    Selectors deliberately try flow2's default English placeholder
    text first (stable across installs that don't localize the login
    screen) and fall back to input[type=password]/the first
    text-like input in the form, since some installs may run flow2 in
    a different locale.
    """
    page.goto(FLOW2_URL, wait_until="networkidle", timeout=30000)

    password_field = _find_first(page, [
        'input[placeholder="Password" i]',
        'input[type="password"]',
    ])
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
    login_button.click(force=True)

    # no single stable "you are logged in" DOM marker is guaranteed
    # across custom UI configs, so wait for the password field to
    # disappear (the login form unmounts on success) instead of
    # asserting on any specific post-login content.
    password_field.wait_for(state="detached", timeout=20000)
    page.wait_for_timeout(1000)
    return page


@pytest.fixture
def picture_fixture_path():
    return os.path.join(os.path.dirname(__file__), "fixtures", "test_picture.png")


@pytest.fixture
def video_fixture_path():
    return os.path.join(os.path.dirname(__file__), "fixtures", "test_video.mp4")


def wait_until(fn, timeout, interval=3, description="condition"):
    """Poll fn() until it returns a truthy value or timeout (seconds) elapses."""
    deadline = time.monotonic() + timeout
    last_result = None
    while time.monotonic() < deadline:
        last_result = fn()
        if last_result:
            return last_result
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for: {description}")
