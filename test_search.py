"""
Search and the top-bar file-type filter (image/video/document/audio
icons). Both a real-UI smoke check and a structural invariant check
that reaches into the app's own already-authenticated API client
(`window.flow`, flow2's felib.js instance every page already has once
logged in) rather than clicking the filter icons directly.

That's a deliberate choice, not a shortcut: the filter icons' exact
markup/classes/icon set can differ across flow2 versions and skins
("jede" install, including old ones, per this suite's whole point),
but the request shape they build - {field:"media", type:"CONTAINS",
value:"video"} - is flow2's own client-side implementation
(store/actions/search.js's getSearchFilter()) talking to
window.flow.getClipsByFulltext(), so driving it directly still
exercises the exact same backend code path a real click would, without
being fragile to DOM changes between versions.

`clip.media` (read via c.getMedia()) is a *built-in* field FlowCenter
always populates from `spots.media` for every clip response,
independent of any custom_metadata_def - unlike custom metadata
fields, it's safe to read on any install. This is what this suite
uses to catch the exact bug that motivated it: a "videos only" filter
silently returning every clip (including ones whose own media field
never contained "video" at all) because the install's soapapidef
never mapped "media" as a searchable field, so the backend couldn't
resolve the filter and dropped it - see this repo's commit 22d6f9c.
"""
from conftest import assert_no_leaked_error
from perf import timed


def _search_via_flow(page, media_filter=None):
    """
    Run a fulltext search the same way flow2's own top search bar
    does, optionally with a single file-type filter active. Returns a
    list of {id, media: [...]}.
    """
    fields = []
    if media_filter:
        fields.append({"field": "media", "type": "CONTAINS", "value": media_filter})
    with timed("search_getClipsByFulltext", filter=media_filter or "none"):
        result = page.evaluate(
            """async (fields) => {
                const res = await window.flow.getClipsByFulltext('', { fields });
                const clips = res.objects ? res.objects.asArray() : res;
                return clips.map(c => ({
                    id: c.getId ? c.getId() : c.data.id,
                    media: c.getMedia ? (c.getMedia().asArray ? c.getMedia().asArray() : c.getMedia()) : (c.data.media || ''),
                }));
            }""",
            fields,
        )
    return result


def test_fulltext_search_via_ui_runs_without_error(logged_in_page):
    """Exercises the real search box, not the API client directly."""
    search_box = logged_in_page.locator(
        'input[placeholder*="Suchbegriff" i], input[placeholder*="search" i]'
    ).first
    search_box.wait_for(state="visible", timeout=10000)
    search_box.click()
    search_box.type("a", delay=30)
    search_box.press("Enter")
    logged_in_page.wait_for_timeout(2000)
    assert_no_leaked_error(logged_in_page.content())
    real_errors = [e for e in logged_in_page.console_errors if "autocomplete" not in e.lower()]
    assert not real_errors, f"search triggered JS console errors: {real_errors}"


def test_type_filter_never_returns_more_than_unfiltered(logged_in_page):
    unfiltered = _search_via_flow(logged_in_page)
    for media_type in ("video", "pictures", "audio", "other"):
        filtered = _search_via_flow(logged_in_page, media_type)
        assert len(filtered) <= len(unfiltered), (
            f'"{media_type}"-only search returned {len(filtered)} clips, '
            f"more than the {len(unfiltered)} an unfiltered search returned - "
            f"the filter is not narrowing results at all (see this module's docstring)"
        )


def test_type_filter_results_actually_match_their_media_field(logged_in_page):
    """
    The precise regression check: every clip a "video"-only search
    returns must itself be tagged "video" in its own (built-in) media
    field, and likewise for "pictures" - not just "the search returned
    fewer rows than everything", but "the rows it returned are
    actually the right ones". Skips a media_type entirely if the
    install's library doesn't have any content of that type at all
    (nothing to assert wrong about in that case).
    """
    for media_type in ("video", "pictures", "audio"):
        filtered = _search_via_flow(logged_in_page, media_type)
        if not filtered:
            continue
        mismatched = [c for c in filtered if media_type not in (c["media"] or [])]
        assert not mismatched, (
            f'"{media_type}"-only search returned clip(s) whose own media field '
            f'does not contain "{media_type}": {mismatched} - the search filter is '
            f"not actually being applied server-side (likely an unmapped custom "
            f'"media" search field in the install\'s soapapidef, see this module\'s '
            f"docstring)"
        )
