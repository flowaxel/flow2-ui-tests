"""
Login: the one thing every flow2 install absolutely must get right.
No custom-metadata assumptions here at all - just the auth/WS flow.
"""
from conftest import FLOW2_URL, FLOW2_USER, FLOW2_PASSWORD, _find_first, assert_no_leaked_error


def test_login_page_loads(page):
    page.goto(FLOW2_URL, wait_until="networkidle", timeout=30000)
    _find_first(page, ['input[placeholder="Password" i]', 'input[type="password"]'])
    assert_no_leaked_error(page.content())


def test_websocket_connects(page):
    """
    The password field starts disabled and only becomes usable once
    flow2's frontend WebSocket connection to the backend succeeds -
    this is the same mechanism a real, unrelated bug broke this
    session (felib.js's getSocket() always evaluating
    readyState===WebSocket.OPEN as false). A password field that never
    enables means the WS transport is broken, independent of whether
    the typed credentials would even be correct.
    """
    page.goto(FLOW2_URL, wait_until="networkidle", timeout=30000)
    password_field = _find_first(page, ['input[placeholder="Password" i]', 'input[type="password"]'])
    page.wait_for_function(
        "el => !el.disabled", arg=password_field.element_handle(), timeout=20000
    )


def test_login_succeeds_with_valid_credentials(logged_in_page):
    # the login form itself unmounts on success - logged_in_page
    # already waited for that, so getting here at all is the
    # assertion. Just double check nothing leaked visibly afterward.
    assert_no_leaked_error(logged_in_page.content())


def test_login_rejects_wrong_password(page):
    page.goto(FLOW2_URL, wait_until="networkidle", timeout=30000)
    password_field = _find_first(page, ['input[placeholder="Password" i]', 'input[type="password"]'])
    page.wait_for_function("el => !el.disabled", arg=password_field.element_handle(), timeout=20000)
    username_field = _find_first(page, [
        'input[placeholder="Username" i]',
        'input[type="text"]:visible, input[type="email"]:visible',
    ])
    username_field.click()
    username_field.type(FLOW2_USER, delay=20)
    password_field.click()
    password_field.type("definitely-the-wrong-password", delay=20)
    login_button = _find_first(page, [
        'button:has-text("Log in")', 'button:has-text("Login")',
        'button:has-text("Anmelden")', 'button[type="submit"]',
    ])
    login_button.click(force=True)
    page.wait_for_timeout(3000)
    # a rejected login must NOT unmount the login form - the password
    # field (or the whole form) has to still be there/visible.
    assert password_field.is_visible(), "login form disappeared after a wrong password - login was not actually rejected"
