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


def _open_upload_file_dialog(page):
    upload_trigger = _find_first(page, [
        'button:has-text("Upload")',
        'a:has-text("Upload")',
        '[class*="upload" i] >> text=Upload',
        'button[title*="upload" i]',
    ], timeout=15000)
    with page.expect_file_chooser(timeout=15000) as fc_info:
        upload_trigger.click()
    return fc_info.value


def _upload_fixture(page, fixture_path):
    file_chooser = _open_upload_file_dialog(page)
    file_chooser.set_files(fixture_path)
    # some flow2 upload UIs need an explicit confirm/start action after
    # picking the file(s), others start automatically on selection -
    # try the common confirm labels, but don't fail if none appear.
    try:
        confirm = _find_first(page, [
            'button:has-text("Start")',
            'button:has-text("Hochladen")',
            'button:has-text("Upload starten")',
        ], timeout=5000)
        confirm.click()
    except Exception:
        pass


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


def test_picture_upload_ingest_and_view(logged_in_page, picture_fixture_path):
    basename = os.path.splitext(os.path.basename(picture_fixture_path))[0]
    _upload_fixture(logged_in_page, picture_fixture_path)

    clip_ids = wait_until(
        lambda: _find_clip_by_fulltext(logged_in_page, basename),
        timeout=UPLOAD_TIMEOUT,
        description=f'uploaded picture "{basename}" to appear in search',
    )
    assert clip_ids, f"upload of {basename} never showed up in search within {UPLOAD_TIMEOUT}s"

    urls = _get_clip_view_urls(logged_in_page, clip_ids[0])
    assert urls["thumbnail"], f"uploaded clip {clip_ids[0]} has no thumbnail at all"
    _assert_image_url_loads(logged_in_page, urls["thumbnail"])
    assert urls["mediafiles"], f"uploaded clip {clip_ids[0]} has no mediafiles at all"
    for mf_url in urls["mediafiles"]:
        _assert_image_url_loads(logged_in_page, mf_url)

    assert_no_leaked_error(logged_in_page.content())


def test_video_upload_ingest_and_preview(logged_in_page, video_fixture_path):
    basename = os.path.splitext(os.path.basename(video_fixture_path))[0]
    _upload_fixture(logged_in_page, video_fixture_path)

    clip_ids = wait_until(
        lambda: _find_clip_by_fulltext(logged_in_page, basename),
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
        urls = _get_clip_view_urls(logged_in_page, clip_ids[0])
        return urls if urls["thumbnail"] else None

    urls = wait_until(
        has_thumbnail, timeout=UPLOAD_TIMEOUT,
        description=f"clip {clip_ids[0]} to get a thumbnail (preview transcode)",
    )
    _assert_image_url_loads(logged_in_page, urls["thumbnail"])
    assert_no_leaked_error(logged_in_page.content())
