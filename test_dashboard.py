"""
Dashboard: loads without a leaked backend error or a client-side JS
exception, and every thumbnail image it renders actually loads (not a
broken image). Says nothing about *what* content is on the dashboard -
that's entirely up to the install's own data and metadata config.
"""
from conftest import assert_no_leaked_error


def test_dashboard_renders_without_leaked_error(logged_in_page):
    assert_no_leaked_error(logged_in_page.content())


def test_dashboard_has_no_console_errors(logged_in_page):
    # a few known-benign warnings (e.g. missing autocomplete
    # attributes) are not failures - only hard errors are.
    real_errors = [
        e for e in logged_in_page.console_errors
        if "autocomplete" not in e.lower()
    ]
    assert not real_errors, f"dashboard logged JS console errors: {real_errors}"


def test_visible_thumbnails_all_load(logged_in_page):
    """
    Every <img> visible on the dashboard right after login (whatever
    is actually in this install's library) must be a real, loaded
    image - not a broken/zero-size one. This is the general form of
    the "picture not found on click-through" bug this suite exists
    to catch: here, applied to whatever thumbnails the dashboard
    itself renders rather than one specific uploaded test file.
    """
    logged_in_page.wait_for_timeout(2000)  # let async thumbnail loads settle
    dims = logged_in_page.eval_on_selector_all(
        "img",
        """imgs => imgs
            .filter(i => i.offsetParent !== null)  // actually visible, not display:none
            .filter(i => i.naturalWidth !== undefined)
            .map(i => ({src: i.src, w: i.naturalWidth, h: i.naturalHeight, complete: i.complete}))
        """,
    )
    broken = [d for d in dims if d["complete"] and (d["w"] == 0 or d["h"] == 0)]
    assert not broken, f"dashboard has broken/zero-size images: {broken}"
