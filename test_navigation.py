"""
Broad, shallow coverage of flow2's other main pages: each one loads
without a leaked backend error or a JS console exception. Deliberately
NOT deep per-page - this is the "does the page render at all" tier,
one step up from test_dashboard.py's single page, for the pages every
flow2 install has regardless of custom_metadata_def (its own
navigation menu is fixed UI chrome, not customer-configured).

Navigation goes through the user menu dropdown (click the username,
then the link) rather than a raw page.goto() to a sub-route: flow2 is
a client-side-routed SPA, and a hard navigation to some routes has
been observed to lose the just-established login session (redirecting
back to the login screen) even though the exact same route reached via
an in-app link works fine - see open_clip_details()'s own docstring
for the general pattern (this app's routing doesn't always behave like
plain URLs) that motivated checking here too, rather than assuming
page.goto() is equivalent.
"""
from conftest import assert_no_leaked_error


def _open_user_menu(page):
    page.click("text=admin", force=True, timeout=5000)
    page.wait_for_timeout(400)


def _check_page(page, label):
    assert_no_leaked_error(page.content())
    real_errors = [e for e in page.console_errors if "autocomplete" not in e.lower()]
    assert not real_errors, f"{label} page logged JS console errors: {real_errors}"


def test_settings_page_loads(logged_in_page):
    _open_user_menu(logged_in_page)
    logged_in_page.locator('a:has-text("Einstellungen"), a:has-text("Settings")').first.click()
    logged_in_page.wait_for_timeout(2000)
    _check_page(logged_in_page, "Settings/Einstellungen")


def test_administration_page_loads(logged_in_page):
    _open_user_menu(logged_in_page)
    admin_link = logged_in_page.locator('a:has-text("Administration")').first
    if admin_link.count() == 0:
        import pytest
        pytest.skip("no Administration link in the user menu - test user likely lacks admin rights")
    admin_link.click()
    logged_in_page.wait_for_timeout(2000)
    _check_page(logged_in_page, "Administration")


def test_projects_page_loads(logged_in_page):
    logged_in_page.locator('a:has-text("Projekte"), a:has-text("Projects")').first.click(force=True)
    logged_in_page.wait_for_timeout(2000)
    _check_page(logged_in_page, "Projects/Projekte")


def test_rooms_page_loads(logged_in_page):
    logged_in_page.locator('a:has-text("Rooms")').first.click(force=True)
    logged_in_page.wait_for_timeout(2000)
    _check_page(logged_in_page, "Rooms")


def test_logout_returns_to_login(logged_in_page):
    _open_user_menu(logged_in_page)
    logged_in_page.locator('a:has-text("Abmelden"), a:has-text("Log out"), a:has-text("Logout")').first.click()
    logged_in_page.wait_for_timeout(2000)
    password_field_back = logged_in_page.locator(
        'input[placeholder="Password" i], input[type="password"]'
    ).first
    assert password_field_back.is_visible(), "logging out did not return to the login screen"
    _check_page(logged_in_page, "post-logout")
