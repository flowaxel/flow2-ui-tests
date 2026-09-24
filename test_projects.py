"""
Projects: creates a real project (see conftest.py's `ensure_test_project`)
and checks its detail page actually shows it correctly.

Deliberately does NOT test editing project metadata after creation: see
`ensure_test_project`'s own docstring for how that was confirmed, by
reading this install's own bundled React source, to not be a feature
this flow2 build's Project detail page exposes at all (no input field,
no pencil/save icon, no edit menu entry - a plain read-only summary).
Testing a save round trip here would mean testing something that
doesn't exist in the UI; this checks what actually does.
"""
from conftest import assert_no_leaked_error


def _open_project_by_id(page, project_id):
    page.locator('a:has-text("Projekte"), a:has-text("Projects")').first.click(force=True)
    page.wait_for_timeout(1500)
    page.locator(f'button[class*="ProjectList_SingleProject"][data-id="{project_id}"]').first.dblclick(force=True)
    page.wait_for_url("**/project/**", timeout=15000)
    page.wait_for_timeout(1500)


def test_project_detail_page_shows_correct_name(logged_in_page, ensure_test_project):
    _open_project_by_id(logged_in_page, ensure_test_project["id"])
    assert_no_leaked_error(logged_in_page.content())
    real_errors = [e for e in logged_in_page.console_errors if "autocomplete" not in e.lower()]
    assert not real_errors, f"project detail page logged JS console errors: {real_errors}"

    shown_name = logged_in_page.evaluate(
        """(expected) => {
            const els = Array.from(document.querySelectorAll(`[data-text="${expected}"]`));
            return els.length ? els[0].textContent.trim() : null;
        }""",
        ensure_test_project["requested_name"],
    )
    assert shown_name == ensure_test_project["requested_name"], (
        f"project {ensure_test_project['id']} detail page doesn't show the name "
        f"it was created with: expected {ensure_test_project['requested_name']!r}, "
        f"found {shown_name!r}"
    )
