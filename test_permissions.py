"""
Admin vs. restricted-user rights matrix: verifies that flow2's own
granting/permission system actually changes what's rendered, not just
that the granting *config* looks right in isolation.

Uses a second, low-privilege account (LOWPRIV_USER, created on demand -
see conftest.py's `ensure_lowpriv_user`) rather than trusting the
backend's own granting API dump: this suite has already found, on the
real install it was built against, cases where a permission-gated
*feature* (metadata field saves) behaved differently from what a config
dump alone would suggest - so every check here compares actual rendered
UI/console-visible behavior between the two accounts, not just JSON.

Every test here is skipped, not failed, if LOWPRIV_USER couldn't be
created (see `ensure_lowpriv_user`'s own docstring for the concrete
reason found on this repo's own reference install: even the level6 admin
account lacked the `fc_edituser` server-wide grant needed to create any
other user at all, with no install-time step that sets it and no UI to
set it either - fixed for that install via a direct `edituseroptions`
SOAP call, not something this suite can safely automate itself).
"""
from conftest import assert_no_leaked_error, open_clip_details, FLOW2_USER


def _open_user_menu(page, username):
    page.click(f"text={username}", force=True, timeout=5000)
    page.wait_for_timeout(400)


def _find_clip(page):
    """Same 'first clip that's both in the API results and actually rendered' logic as test_clipdetails.py."""
    return page.evaluate(
        """async () => {
            const res = await window.flow.getClipsByFulltext('', {});
            const clips = res.objects ? res.objects.asArray() : res;
            const renderedSrcs = Array.from(document.querySelectorAll('img'))
                .filter(i => i.src.includes('thumbnail.cgi'))
                .map(i => i.src);
            for (const c of clips) {
                const id = c.getId ? c.getId() : c.data.id;
                const thumb = c.mainthumbnail && c.mainthumbnail.url;
                if (!thumb) continue;
                const match = thumb.match(/file=[^&]*\\/([^&\\/]+)/);
                const fragment = match ? match[1] : String(id);
                if (renderedSrcs.some(src => src.includes(fragment))) {
                    return { id, fragment };
                }
            }
            return null;
        }"""
    )


def test_administration_link_present_for_admin_user(logged_in_page):
    """
    Sanity/contrast check for the restricted-user test below: the admin
    test account (FLOW2_USER) is assumed throughout this suite to
    actually have admin rights - if this ever stops being true (wrong
    account, or its role got downgraded), every other permission
    comparison in this file becomes meaningless without this failing
    loudly first.
    """
    _open_user_menu(logged_in_page, FLOW2_USER)
    admin_link = logged_in_page.locator('a:has-text("Administration")')
    assert admin_link.count() > 0, (
        "the admin test account (FLOW2_USER) has no Administration link - "
        "either it isn't actually an admin account, or its role changed"
    )


def test_no_administration_link_for_lowpriv_user(lowpriv_logged_in_page, ensure_lowpriv_user):
    _open_user_menu(lowpriv_logged_in_page, ensure_lowpriv_user)
    admin_link = lowpriv_logged_in_page.locator('a:has-text("Administration")')
    assert admin_link.count() == 0, (
        f"restricted account '{ensure_lowpriv_user}' can see the Administration "
        "link - granting isn't actually restricting admin-menu visibility"
    )
    assert_no_leaked_error(lowpriv_logged_in_page.content())


def test_lowpriv_user_has_fewer_delete_controls_on_clip_detail(
    logged_in_page, lowpriv_logged_in_page, ensure_lowpriv_user
):
    """
    Opens the *same* clip's detail page as both accounts and compares how
    many trash-icon delete controls are rendered. Deliberately a
    less-than comparison, not "zero for lowpriv": a clip detail page can
    render more than one trash icon (e.g. one per attached media file,
    alongside the main "delete this clip" toolbar button), and only the
    main clip-delete one is necessarily gated by the `deleteclip`
    granting rule this test is actually trying to exercise - confirmed
    empirically against the reference install (admin: 3 trash icons,
    the same clip as the restricted account: 2).
    """
    clip = _find_clip(logged_in_page)
    if not clip:
        import pytest
        pytest.skip("no clip in this install's library to open a detail page for")

    open_clip_details(logged_in_page, clip["fragment"])
    admin_trash_count = logged_in_page.locator('svg[data-icon="trash"]').count()

    open_clip_details(lowpriv_logged_in_page, clip["fragment"])
    lowpriv_trash_count = lowpriv_logged_in_page.locator('svg[data-icon="trash"]').count()

    assert lowpriv_trash_count < admin_trash_count, (
        f"restricted account '{ensure_lowpriv_user}' sees the same number of "
        f"delete controls on clip {clip['id']} as admin ({lowpriv_trash_count} "
        f"vs {admin_trash_count}) - the deleteclip granting rule doesn't appear "
        "to change what's actually rendered"
    )
    assert_no_leaked_error(lowpriv_logged_in_page.content())
