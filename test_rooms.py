"""
Rooms: creates a real room and opens its detail page by id (see
conftest.py's `ensure_test_room` for why by id, not by name).

No edit-round-trip test here, same reasoning as test_projects.py:
Flow2/pages/Rooms/RoomView.js's own "Room details" panel is the same
plain read-only <p data-text=...> pattern as ProjectView.js, confirmed
by reading this install's own bundled source - nothing to save-round-
trip test.

Room *creation* itself, though, has a real bug worth testing directly -
see `test_room_creation_persists_the_given_title` below.
"""
from conftest import assert_no_leaked_error


def _open_room_by_id(page, room_id):
    page.locator('a:has-text("Rooms")').first.click(force=True)
    page.wait_for_timeout(1500)
    page.locator(f'a[href*="/room/{room_id}"]').first.click(force=True)
    page.wait_for_url("**/room/**", timeout=15000)
    page.wait_for_timeout(1500)


def test_room_detail_page_loads(logged_in_page, ensure_test_room):
    _open_room_by_id(logged_in_page, ensure_test_room["id"])
    assert_no_leaked_error(logged_in_page.content())
    real_errors = [e for e in logged_in_page.console_errors if "autocomplete" not in e.lower()]
    assert not real_errors, f"room detail page logged JS console errors: {real_errors}"


def test_room_creation_persists_the_given_title(logged_in_page, ensure_test_room):
    """
    The room-creation popup's title field *is* sent correctly to the
    backend (confirmed via the WebSocket frame:
    {"action":"showroomcreate","params":{"metadata":{"title":"...",
    ...}}} - the exact name this fixture asked for, not empty, not
    mangled). What comes back for the newly created room's `title` (and
    `owner`, `roomtype`, and nearly every other metadata field) is
    instead the literal string "notset" - not the submitted value, not
    null/empty either. This is a real, install-side bug in room
    creation, not a UI-rendering issue: `data-text` on the room detail
    page reflects exactly what the backend actually stored, and the
    backend's own showroomcreate response already showed "notset"
    before this page even re-fetched anything.
    """
    _open_room_by_id(logged_in_page, ensure_test_room["id"])
    shown_name = logged_in_page.evaluate(
        """(expected) => {
            const els = Array.from(document.querySelectorAll(`[data-text="${expected}"]`));
            return els.length ? els[0].textContent.trim() : null;
        }""",
        ensure_test_room["requested_name"],
    )
    assert shown_name == ensure_test_room["requested_name"], (
        f"room {ensure_test_room['id']} was created with title="
        f"{ensure_test_room['requested_name']!r}, but its detail page shows "
        f"{shown_name!r} instead - room creation isn't actually persisting "
        "the title (or any of several other metadata fields) it's given"
    )
