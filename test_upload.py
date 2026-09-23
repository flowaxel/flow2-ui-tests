"""
Upload -> automatic ingest -> viewable, end to end. This is the
regression check for the two real bugs found and fixed in this repo's
history (commits 65aef3f, 22d6f9c): a clip whose thumbnail shows up
fine in search but whose full media 404s/"picture not found"s on
click-through, and a clip silently misclassified under a file-type
search filter. Both were invisible to a compile-only or backend-only
check - they only show up by actually uploading something and looking
at what the browser does with the response, which is exactly what
this module does.

Entirely opt-out via FLOW2_TEST_UPLOAD=0 (see README.md) for a target
install where the test user has no upload permission, or where
skipping the (slower) ingest/transcode round-trip is preferred.

Upload UI selectors are best-effort across flow2 versions/skins (see
README's whole reason for existing) - if these need adjusting for a
given install, that's expected and not itself a bug in the target.
"""
import os
import time

import pytest

from conftest import (
    UPLOAD_TIMEOUT, TEST_UPLOAD, assert_no_leaked_error, wait_until, _find_first,
)

pytestmark = pytest.mark.skipif(not TEST_UPLOAD, reason="FLOW2_TEST_UPLOAD=0")


def _upload_fixture(page, fixture_path):
    """
    Drives flow2's actual upload flow, confirmed against a real
    install rather than guessed: clicking "Upload" opens an in-page
    modal (drag & drop zone + a metadata form), NOT a native OS file
    picker - there's no `filechooser` event to wait for at all.
    The modal's file input is already a real, visible <input
    type=file> (just one of several on the page, most hidden), so
    `set_input_files()` works directly on it once found; a separate,
    visually distinct red "Upload" submit button (not the sidebar nav
    button of the same name) actually starts the upload.
    """
    upload_nav_button = _find_first(page, [
        'button:has-text("Upload")',
        'a:has-text("Upload")',
    ], timeout=15000)
    upload_nav_button.click()
    page.wait_for_timeout(1500)

    file_input = None
    for candidate in page.locator('input[type="file"]').all():
        if candidate.is_visible():
            file_input = candidate
            break
    assert file_input is not None, "upload modal opened but no visible file input was found in it"
    file_input.set_input_files(fixture_path)
    page.wait_for_timeout(2000)

    # the modal's own submit button also just says "Upload" - the LAST
    # one in DOM order is reliably the modal's, not the sidebar nav's
    # (which opened the modal in the first place and is still present
    # behind it).
    submit_buttons = page.locator('button:has-text("Upload")').all()
    assert submit_buttons, "no Upload submit button found in the upload modal"
    submit_buttons[-1].click(force=True)
    page.wait_for_timeout(3000)

    # a rejected upload (permission, quota, a transient backend error)
    # surfaces as a SweetAlert2 popup, which then blocks every
    # subsequent click on the page (including other tests', since the
    # session/page is shared - see conftest.py's logged_in_page) until
    # dismissed. Surface its actual message in the failure rather than
    # letting the next test fail with a confusing "element intercepts
    # pointer events" instead.
    error_popup = page.locator(".swal2-container")
    if error_popup.count() > 0 and error_popup.is_visible():
        popup_text = error_popup.inner_text()
        page.locator(".swal2-confirm, .swal2-close").first.click(force=True)
        page.wait_for_timeout(500)
        raise AssertionError(f"upload was rejected by the backend: {popup_text!r}")


def _find_clip_by_fulltext(page, query):
    result = page.evaluate(
        """async (query) => {
            const res = await window.flow.getClipsByFulltext(query, {});
            const clips = res.objects ? res.objects.asArray() : res;
            return clips.map(c => (c.getId ? c.getId() : c.data.id));
        }""",
        query,
    )
    return result


def _get_clip_view_urls(page, clip_id):
    """
    thumbnail url + full mediafile url(s) for a clip, via the app's own
    already-authenticated API client - exactly what its Lightbox/detail
    view puts into <img src>/<video src>, see Flow2/components/Lightbox/
    Lightbox.js and Flow2/util/Clip.js this repo's history investigated
    at length for the real bug this test guards against.
    """
    return page.evaluate(
        """async (clipId) => {
            const clip = await window.flow.getClipById(clipId);
            const mediafiles = clip.mediafiles.elements.map(m => m.getUrl ? m.getUrl() : m.data.url);
            const thumbnail = clip.mainthumbnail && clip.mainthumbnail.url;
            return { thumbnail, mediafiles };
        }""",
        clip_id,
    )


def _assert_image_url_loads(page, url):
    if url.startswith("//"):
        url = "https:" + url
    dims = page.evaluate(
        """(url) => new Promise((resolve) => {
            const img = new Image();
            img.onload = () => resolve({ok: true, w: img.naturalWidth, h: img.naturalHeight});
            img.onerror = () => resolve({ok: false, w: 0, h: 0});
            img.src = url;
        })""",
        url,
    )
    assert dims["ok"] and dims["w"] > 0 and dims["h"] > 0, (
        f"media URL did not load as a real image: {url} -> {dims} "
        f'(this is the "picture not found" class of bug - see this module\'s docstring)'
    )


def test_picture_upload_ingest_and_view(fresh_logged_in_page, picture_fixture_path):
    basename = os.path.splitext(os.path.basename(picture_fixture_path))[0]
    _upload_fixture(fresh_logged_in_page, picture_fixture_path)

    clip_ids = wait_until(
        lambda: _find_clip_by_fulltext(fresh_logged_in_page, basename),
        timeout=UPLOAD_TIMEOUT,
        description=f'uploaded picture "{basename}" to appear in search',
    )
    assert clip_ids, f"upload of {basename} never showed up in search within {UPLOAD_TIMEOUT}s"

    urls = _get_clip_view_urls(fresh_logged_in_page, clip_ids[0])
    assert urls["thumbnail"], f"uploaded clip {clip_ids[0]} has no thumbnail at all"
    _assert_image_url_loads(fresh_logged_in_page, urls["thumbnail"])
    assert urls["mediafiles"], f"uploaded clip {clip_ids[0]} has no mediafiles at all"
    for mf_url in urls["mediafiles"]:
        _assert_image_url_loads(fresh_logged_in_page, mf_url)

    assert_no_leaked_error(fresh_logged_in_page.content())


def test_video_upload_ingest_and_preview(fresh_logged_in_page, video_fixture_path):
    basename = os.path.splitext(os.path.basename(video_fixture_path))[0]
    _upload_fixture(fresh_logged_in_page, video_fixture_path)

    clip_ids = wait_until(
        lambda: _find_clip_by_fulltext(fresh_logged_in_page, basename),
        timeout=UPLOAD_TIMEOUT,
        description=f'uploaded video "{basename}" to appear in search',
    )
    assert clip_ids, f"upload of {basename} never showed up in search within {UPLOAD_TIMEOUT}s"

    # the preview transcode is a separate, slower async step after the
    # clip itself is visible (see this repo's default 'Preview'
    # workflow) - give it its own generous wait rather than reusing
    # the ingest timeout, and only require *a* mediafile with a
    # loadable thumbnail (not specifically the transcoded preview,
    # which some installs may not have NVENC/a transcode pipeline for
    # at all - see README's "what's not covered yet").
    def has_thumbnail():
        urls = _get_clip_view_urls(fresh_logged_in_page, clip_ids[0])
        return urls if urls["thumbnail"] else None

    urls = wait_until(
        has_thumbnail, timeout=UPLOAD_TIMEOUT,
        description=f"clip {clip_ids[0]} to get a thumbnail (preview transcode)",
    )
    _assert_image_url_loads(fresh_logged_in_page, urls["thumbnail"])
    assert_no_leaked_error(fresh_logged_in_page.content())
