"""
The clip detail page (/clipdetails/<id>): opening a clip, its main
media actually rendering (the exact "picture not found" class of bug
this suite exists to catch - see this repo's commit a802775, a SECOND,
unrelated bug from the one test_upload.py's own assertions cover,
found in a code path that builds its own thumbnail URL by hand instead
of calling mediafile.getUrl()), and the metadata edit-and-save round
trip actually persisting server-side, not just changing in the DOM.

Requires at least one existing, findable clip - skips (not fails) if
none is found, since an entirely empty library has nothing to open a
detail page for. test_upload.py, if enabled, guarantees one exists;
run this suite's own picture upload first against an empty install if
these tests report nothing to work with.
"""
import time

import pytest

from conftest import (
    assert_no_leaked_error, open_clip_details, enter_metadata_edit_mode,
    save_metadata_edit, metadata_field_input,
)


def _find_any_clip(page):
    """First clip id+thumbnail-src-fragment the app's own API can find, or None."""
    return page.evaluate(
        """async () => {
            const res = await window.flow.getClipsByFulltext('', {});
            const clips = res.objects ? res.objects.asArray() : res;
            if (!clips.length) return null;
            const c = clips[0];
            const id = c.getId ? c.getId() : c.data.id;
            const thumb = c.mainthumbnail && c.mainthumbnail.url;
            if (!thumb) return null;
            const match = thumb.match(/file=[^&]*\\/([^&\\/]+)/);
            return { id, fragment: match ? match[1] : String(id) };
        }"""
    )


@pytest.fixture
def any_clip(logged_in_page):
    clip = _find_any_clip(logged_in_page)
    if not clip:
        pytest.skip("no clip in this install's library to open a detail page for")
    return clip


def test_clip_detail_page_opens_and_main_media_loads(logged_in_page, any_clip):
    open_clip_details(logged_in_page, any_clip["fragment"])
    assert f"/clipdetails/{any_clip['id']}" in logged_in_page.url

    # MediaOutput (Flow2/pages/Clip/ClipDetails.js) always gives the
    # main visible image/video the id "MainThumb" regardless of
    # picture/audio/other type (video uses a <video>-based player
    # instead - handled separately below).
    main_img = logged_in_page.evaluate(
        """() => {
            const el = document.getElementById('MainThumb');
            if (!el) return null;
            return { tag: el.tagName, w: el.naturalWidth, h: el.naturalHeight, complete: el.complete };
        }"""
    )
    video_present = logged_in_page.locator("video").count() > 0

    assert main_img or video_present, "clip detail page shows neither a #MainThumb image nor a <video> player"
    if main_img and main_img["tag"] == "IMG":
        assert main_img["complete"] and main_img["w"] > 0 and main_img["h"] > 0, (
            f"clip detail page's main image did not load: {main_img} "
            '(this is the "picture not found" class of bug - see this module\'s docstring)'
        )

    assert_no_leaked_error(logged_in_page.content())
    real_errors = [e for e in logged_in_page.console_errors if "autocomplete" not in e.lower()]
    assert not real_errors, f"clip detail page logged JS console errors: {real_errors}"


def test_metadata_edit_and_save_persists(logged_in_page, any_clip):
    """
    Types a unique value into the title field, saves, and verifies the
    change against a *fresh* fetch of the clip (not just the DOM) -
    catching a save button that changes the visible field but never
    actually calls back to the server, which looks identical to a
    working save if you only check the input's value afterward.
    Restores the original title afterward either way, so this doesn't
    leave test data behind in someone's real library.
    """
    open_clip_details(logged_in_page, any_clip["fragment"])
    enter_metadata_edit_mode(logged_in_page)

    title_field = metadata_field_input(logged_in_page, ["Titel", "Title"])
    title_field.wait_for(state="visible", timeout=10000)
    original_title = title_field.input_value()

    new_title = f"flow2-ui-tests autotest {int(time.time())}"
    try:
        title_field.fill(new_title)
        assert title_field.input_value() == new_title, "typed title did not register in the input field"

        save_metadata_edit(logged_in_page)

        def fetch_title():
            return logged_in_page.evaluate(
                """async (clipId) => {
                    const clip = await window.flow.getClipById(clipId);
                    return clip.metadata ? clip.metadata.get('title') : null;
                }""",
                any_clip["id"],
            )

        saved_title = fetch_title()
        assert saved_title == new_title, (
            f"metadata save did not persist server-side: expected {new_title!r}, "
            f"a fresh fetch of the clip returned {saved_title!r} - the save button "
            "changed the field in the DOM but the backend was never actually updated"
        )
    finally:
        # best-effort restore, even if the assertion above failed
        try:
            enter_metadata_edit_mode(logged_in_page)
            title_field2 = metadata_field_input(logged_in_page, ["Titel", "Title"])
            title_field2.fill(original_title)
            save_metadata_edit(logged_in_page)
        except Exception:
            pass

    assert_no_leaked_error(logged_in_page.content())
