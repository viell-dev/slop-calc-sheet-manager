"""Where keys and ranges start: after Ctrl with a cursor key (#313), and after another window
renamed the cursor's sheet before the list refreshed (#314).

The list consumes its selection keys, so the tree never handles them; it shows the list's cursor
when the list's write runs. That write leaves the tree no range anchor, and the tree makes one at
its cursor for the next Shift or Ctrl+Shift press (`SvImpLBox::SelAllDestrAnch`,
`ImpLBSelEng::CreateAnchor`, read in 26.8.2.2), as VCL's own Ctrl with a cursor key drops its
anchor (`SelectionEngine::CursorPosChanging`). The list's anchor stayed behind at such a key, so a
Ctrl+Shift+click added another range to the picks than the tree had shown: refused when the two
ranges differed in size, and acted on when they did not.

A key revalidated the picks, the cursor and the anchor against the sheets' names. When another
window had renamed the cursor's sheet and the list had not refreshed yet, the cursor went, and the
key moved from the first row, picking a sheet the user had never moved to. The rows change only
at a refresh, so the cursor and the anchor keep their rows until then; the renamed sheet itself is
never picked, since its ref no longer proves it (#28).

The real list runs over the simulated peer of `list_peer`, whose native Ctrl+Shift press adds
the rows from the tree's anchor, made at its cursor when it has none, and whose `select` leaves
the tree no anchor.
"""

from typing import Any

import pytest

from sheet_manager.selection import Ref, Selection
from tests.unit.list_peer import (
    DOWN,
    END,
    HOME,
    MOD1,
    PAGEDOWN,
    PAGEUP,
    SHIFT,
    SPACE,
    UP,
    A,
    Book,
    changed,
    click,
    cursor,
    key,
    move_to_top,
    picks,
    queued_click,
    sheet_list,
)

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]
RENAMED = "India"  # Charlie's name after another window renamed it.


def row(name: str) -> int:
    return NAMES.index(name)


def clicked(name: str) -> Any:
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row(name))
    assert picks(owner) == [name] and owner.tree.shown() == [name]
    return owner


def anchor(owner: Any) -> str | None:
    ref = owner._selection.anchor
    return ref.name if ref is not None else None


def refresh(owner: Any) -> None:
    """The document change's refresh, once the schedule's timer is due."""
    changed(owner)
    owner.retry()
    owner.run_queue()


# After Ctrl with a cursor key (#313).


@pytest.mark.parametrize(
    "start,keys,end,shown",
    [
        pytest.param("Alfa", [DOWN] * 4, "Golf", ["Alfa", "Echo", "Foxtrot", "Golf"], id="down"),
        # The ranges from Alfa and from Foxtrot both add three rows: `main` added Bravo to
        # Delta, which the tree never showed.
        pytest.param(
            "Alfa", [DOWN] * 5, "Delta", ["Alfa", "Delta", "Echo", "Foxtrot"], id="same-size"
        ),
        pytest.param(
            "Hotel", [HOME, DOWN], "Delta", ["Bravo", "Charlie", "Delta", "Hotel"], id="home"
        ),
        pytest.param("Alfa", [END, UP, UP], "Echo", ["Alfa", "Echo", "Foxtrot"], id="end"),
        # Ctrl+Page Up and Ctrl+Page Down are Calc's sheet switch, which the list forwards.
    ],
)
def test_a_ctrl_shift_click_after_ctrl_keys_adds_the_range_the_tree_shows(
    start: str, keys: list[int], end: str, shown: list[str]
) -> None:
    """A click, Ctrl with cursor keys, each written before the next input, and a Ctrl+Shift+click:
    the tree adds the rows from its cursor, where the keys' write left it, to the clicked row.
    The list adds the same range, from the cursor, with no notice, and Move to Top moves what the
    tree showed."""
    owner = clicked(start)
    for code in keys:
        key(owner, code, MOD1)
    assert picks(owner) == [start] and anchor(owner) == cursor(owner)
    queued_click(owner, row(end), MOD1 | SHIFT)
    assert owner.tree.shown() == shown, "the tree's range"
    owner.run_queue()
    assert picks(owner) == shown and owner.tree.shown() == shown
    assert owner.notices == [] and cursor(owner) == end
    assert move_to_top(owner) == shown


def test_keys_and_a_shift_click_after_ctrl_keys_start_at_the_cursor() -> None:
    """Alfa clicked and Ctrl+Down four times to Echo. A Shift+Down then picks Echo and Foxtrot,
    as VCL's own handling of these keys would, and Ctrl+Shift+Down adds them to Alfa; a
    Shift+click on Golf picks Echo to Golf. `main` ranged from Alfa each time."""
    for code, modifiers, wanted in [
        (DOWN, SHIFT, ["Echo", "Foxtrot"]),
        (DOWN, MOD1 | SHIFT, ["Alfa", "Echo", "Foxtrot"]),
        (PAGEDOWN, SHIFT, ["Echo", "Foxtrot", "Golf", "Hotel"]),
        (None, SHIFT, ["Echo", "Foxtrot", "Golf"]),
    ]:
        owner = clicked("Alfa")
        for _ in range(4):
            key(owner, DOWN, MOD1)
        if code is None:
            queued_click(owner, row("Golf"), modifiers)
            owner.run_queue()
        else:
            key(owner, code, modifiers)
        assert picks(owner) == wanted and owner.tree.shown() == wanted
        assert anchor(owner) == "Echo"


def test_a_refused_ctrl_key_moves_the_anchor_with_the_cursor() -> None:
    """Alfa picked; Charlie selected through accessibility before any intake, so Ctrl+Down is
    refused: the picks go, with the notice, and the cursor moves to Bravo, the anchor with it. The
    refusal's write clears the tree with its cursor on Bravo, and a Ctrl+Shift+click on Delta then
    adds Bravo to Delta in the tree and in the list. With the anchor left on Alfa, the list's range
    added four rows to the tree's three, and the press was refused too."""
    owner = clicked("Alfa")
    owner.tree.assistive_select("Charlie")
    key(owner, DOWN, MOD1)
    assert picks(owner) == [] and owner.tree.shown() == [] and len(owner.notices) == 1
    assert cursor(owner) == anchor(owner) == "Bravo"
    queued_click(owner, row("Delta"), MOD1 | SHIFT)
    owner.run_queue()
    wanted = ["Bravo", "Charlie", "Delta"]
    assert picks(owner) == wanted and owner.tree.shown() == wanted
    assert len(owner.notices) == 1
    assert move_to_top(owner) == wanted


@pytest.mark.parametrize("modifiers", [MOD1 | SHIFT, SHIFT], ids=["ctrl-shift", "shift"])
def test_a_range_click_before_the_ctrl_keys_write_is_refused(modifiers: int) -> None:
    """Alfa and Charlie picked; Ctrl+Down twice and a Ctrl+Shift+click or Shift+click on Golf,
    which the tree handles before the keys' write, as when LibreOffice is busy. The tree ranges
    from its cursor on Charlie, where it still shows it, and the list's anchor is on Echo now, so
    the press picks nothing: the picks go, with the notice, and the write clears the tree's range.
    Without the hold, the listener ran after that write and added the range from Echo, which the
    tree never showed."""
    owner = clicked("Alfa")
    queued_click(owner, row("Charlie"))
    owner.run_queue()
    for _ in range(2):
        owner.tree_key(DOWN, MOD1)
    queued_click(owner, row("Golf"), modifiers)
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) == 1
    assert move_to_top(owner) is None
    # The refusal moved the cursor and the anchor to Golf, as a refused toggle does, and its
    # write showed them: a range from there acts.
    assert cursor(owner) == anchor(owner) == "Golf"
    queued_click(owner, row("Echo"), MOD1 | SHIFT)
    owner.run_queue()
    assert picks(owner) == ["Echo", "Foxtrot", "Golf"] == owner.tree.shown()


def test_a_range_click_before_a_refused_range_clicks_write_is_refused() -> None:
    """Alfa clicked; Ctrl+Down, and a Ctrl+Shift+click on Charlie handled before the key's write,
    which is refused and moves the list's cursor and anchor to Charlie. Before the refusal's write
    shows that cursor, a Ctrl+Shift+click on Echo ranges natively from the tree's anchor, still
    on Bravo. It is refused too: the list would have added Charlie to Echo (#313's fuzzing)."""
    owner = clicked("Alfa")
    owner.tree_key(DOWN, MOD1)
    queued_click(owner, row("Charlie"), MOD1 | SHIFT)
    while owner.queue:  # The key's write, then the refused click's listeners.
        work, where = owner.queue.pop(0)
        work()
        if where == "a mouse release":
            break
    assert picks(owner) == [] and cursor(owner) == anchor(owner) == "Charlie"
    assert owner.tree.cursor is not owner.tree.node("Charlie"), "the refusal's write ran"
    queued_click(owner, row("Echo"), MOD1 | SHIFT)
    owner.run_queue()
    assert "Charlie" not in picks(owner), "a range from the anchor the tree did not have"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_a_ctrl_click_behind_a_refused_range_click_does_not_toggle_against_its_range() -> None:
    """Nothing picked; Ctrl+Down, then a Ctrl+Shift+click on Alfa and a Ctrl+click on Bravo, all
    before the key's write. The tree adds Alfa from its own cursor and, in its add mode, leaves
    Bravo unselected. The range press is refused; the Ctrl+click's listener must not then pick
    Bravo against picks that lack the range the tree showed, as when the refusal held no toggles
    (#313's fuzzing): toggles are held, as at every refused toggle."""
    owner = sheet_list(Book(list(NAMES)))
    owner.tree_key(DOWN, MOD1)
    queued_click(owner, row("Alfa"), MOD1 | SHIFT)
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert "Bravo" not in picks(owner), "the row the user had just deselected"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


@pytest.mark.parametrize(
    "modifiers,tree",
    [
        pytest.param(MOD1 | SHIFT, ["Alfa", "Bravo", "Charlie"], id="ctrl-shift"),
        pytest.param(SHIFT, ["Charlie"], id="shift"),  # The simulated Shift press: its row.
    ],
)
def test_a_range_click_whose_listener_runs_after_ctrl_keys_is_refused(
    modifiers: int, tree: list[str]
) -> None:
    """Alfa clicked; a Ctrl+Shift+click or Shift+click on Charlie, which the tree handles from its
    cursor on Alfa, and Ctrl+Down three times typed before the press's listener runs, as when
    LibreOffice is busy. The keys moved the list's anchor to Delta, so the listener would have
    ranged from Delta, a sheet the user never selected; it picks nothing, with the notice."""
    owner = clicked("Alfa")
    queued_click(owner, row("Charlie"), modifiers)
    assert owner.tree.shown() == tree
    for _ in range(3):
        owner.tree_key(DOWN, MOD1)
    owner.run_queue()
    assert "Delta" not in picks(owner), "the range from the anchor that later keys moved"
    assert picks(owner) == [] and owner.tree.shown() == []
    # The first Ctrl+Down is refused too, since the press's change waits: each refusal renews the
    # one notice.
    assert len(owner.notices) == 2
    assert move_to_top(owner) is None


def test_a_ctrl_shift_click_after_a_shift_range_adds_as_before() -> None:
    """Control: after a Shift range the anchor stays at its start, and every row up to the cursor
    is picked, so the tree's range from the cursor and the list's from the anchor add alike."""
    for end, wanted in [("Echo", NAMES[1:5]), ("Bravo", NAMES[1:3]), ("Alfa", NAMES[:3])]:
        owner = clicked("Bravo")
        queued_click(owner, row("Charlie"), SHIFT)
        owner.run_queue()
        assert picks(owner) == ["Bravo", "Charlie"] and anchor(owner) == "Bravo"
        queued_click(owner, row(end), MOD1 | SHIFT)
        tree = owner.tree.shown()
        owner.run_queue()
        assert picks(owner) == tree == wanted and owner.notices == []


def test_ctrl_keys_keep_the_picks() -> None:
    """Control: Ctrl with a cursor key still moves only the cursor and keeps the picks, as on
    `main`."""
    owner = clicked("Alfa")
    queued_click(owner, row("Charlie"))
    owner.run_queue()
    for code in (DOWN, DOWN, END, UP, HOME):
        key(owner, code, MOD1)
        assert picks(owner) == ["Alfa", "Charlie"] == owner.tree.shown()
    assert cursor(owner) == "Alfa"
    key(owner, SPACE, MOD1)
    assert picks(owner) == ["Charlie"]


# After another window renamed the cursor's sheet, before the refresh (#314).


def renamed(*keys: tuple[int, int]) -> Any:
    """Charlie clicked; another window renames it; the keys before the list refreshes."""
    owner = clicked("Charlie")
    owner.book.rename("Charlie", RENAMED)
    for code, modifiers in keys:
        key(owner, code, modifiers)
    return owner


@pytest.mark.parametrize(
    "keys,wanted",
    [
        pytest.param([(DOWN, 0)], ["Delta"], id="down"),
        pytest.param([(UP, 0)], ["Bravo"], id="up"),
        pytest.param([(PAGEDOWN, 0)], ["Foxtrot"], id="page-down"),
        pytest.param([(DOWN, SHIFT)], ["Delta"], id="shift-down"),
        pytest.param([(DOWN, MOD1 | SHIFT)], ["Delta"], id="ctrl-shift-down"),
        pytest.param([(END, SHIFT)], NAMES[3:], id="shift-end"),
        pytest.param([(HOME, SHIFT)], ["Alfa", "Bravo"], id="shift-home"),
        pytest.param([(END, SHIFT), (UP, SHIFT)], NAMES[3:7], id="shift-end-up"),
        pytest.param([(DOWN, SHIFT), (UP, SHIFT)], [], id="shift-down-up"),
        pytest.param([(PAGEUP, SHIFT)], ["Alfa", "Bravo"], id="shift-page-up"),
        pytest.param([(DOWN, MOD1), (SPACE, MOD1)], ["Delta"], id="ctrl-down-space"),
        pytest.param([(SPACE, MOD1), (DOWN, 0)], ["Delta"], id="ctrl-space-down"),
        pytest.param([(A, MOD1), (DOWN, 0)], ["Delta"], id="ctrl-a-down"),
        pytest.param([(DOWN, 0), (UP, 0), (DOWN, 0)], ["Delta"], id="down-up-down"),
    ],
)
def test_keys_after_a_rename_of_the_cursors_sheet_move_from_its_row(
    keys: list[tuple[int, int]], wanted: list[str]
) -> None:
    """The keys move from Charlie's row, where the user saw the cursor, and ranges start there;
    the renamed sheet is never picked. After the refresh the list shows India unpicked, and Move
    to Top moves what the keys picked. `main` moved from the first row: Down picked Bravo, and
    Ctrl+Space Alfa."""
    owner = renamed(*keys)
    assert picks(owner) == wanted and owner.tree.shown() == wanted
    refresh(owner)
    assert owner.names()[row("Charlie")] == RENAMED
    assert picks(owner) == wanted and owner.tree.shown() == wanted
    assert RENAMED not in picks(owner)
    assert move_to_top(owner) == (wanted or None)


def test_a_toggle_on_the_renamed_cursors_row_picks_nothing_and_keeps_the_cursor_there() -> None:
    """Space on the renamed sheet's row toggles nothing: the sheet is not picked under the name
    it no longer has. The write shows the cursor on that row, where the next key moves from."""
    owner = renamed((SPACE, MOD1))
    assert picks(owner) == [] and owner.tree.shown() == []
    assert cursor(owner) == "Charlie" and owner.tree.cursor is owner.tree.node("Charlie")
    key(owner, UP, 0)
    assert picks(owner) == ["Bravo"]
    refresh(owner)
    assert move_to_top(owner) == ["Bravo"]


def test_a_commands_check_of_its_picks_keeps_the_renamed_cursors_row() -> None:
    """The keyboard menu's check of the picks before the refresh, as every command's, keeps the
    cursor on the renamed sheet's row, as the key handler does: the next key moves from there."""
    owner = renamed((SPACE, MOD1))
    owner.open_menu_for_keyboard()  # Nothing is picked, so no menu opens.
    owner.run_queue()
    assert cursor(owner) == "Charlie" and owner.tree.cursor is owner.tree.node("Charlie")
    key(owner, DOWN, 0)
    assert picks(owner) == ["Delta"]


def test_the_refresh_then_drops_the_renamed_cursor() -> None:
    """Control: the refresh drops the cursor and the anchor as it drops picks, and its write puts
    the cursor on the first pick, as on `main`. Two Ctrl+clicks on Delta leave both on it."""
    owner = clicked("Alfa")
    for _ in range(2):
        queued_click(owner, row("Delta"))
        owner.run_queue()
    assert picks(owner) == ["Alfa"] and cursor(owner) == anchor(owner) == "Delta"
    owner.book.rename("Delta", "Juliett")
    refresh(owner)
    assert picks(owner) == ["Alfa"] and cursor(owner) == "Alfa"
    assert anchor(owner) is None


def test_a_key_after_a_rename_of_another_sheet_acts_as_before() -> None:
    """Control: Foxtrot renamed by another window; Down from Charlie picks Delta, as on `main`."""
    owner = clicked("Charlie")
    owner.book.rename("Foxtrot", "Juliett")
    key(owner, DOWN, 0)
    assert picks(owner) == ["Delta"]


@pytest.mark.parametrize(
    "modifiers,tree,wanted",
    [
        pytest.param(SHIFT, ["Echo"], ["Delta", "Echo"], id="shift"),
        pytest.param(
            MOD1 | SHIFT, ["Charlie", "Delta", "Echo"], ["Delta", "Echo"], id="ctrl-shift"
        ),
    ],
)
def test_a_range_click_after_a_rename_of_its_anchors_sheet_starts_at_its_row(
    modifiers: int, tree: list[str], wanted: list[str]
) -> None:
    """Charlie clicked, then renamed by another window; a Shift+click or a Ctrl+Shift+click on
    Echo ranges from Charlie's row, as the tree's from its cursor there, without the renamed
    sheet. `main` started the range at Echo: the Shift+click picked Echo alone, and the
    Ctrl+Shift+click, whose range then added one row to the tree's two, was refused."""
    owner = clicked("Charlie")
    owner.book.rename("Charlie", RENAMED)
    queued_click(owner, row("Echo"), modifiers)
    assert owner.tree.shown() == tree  # The simulated plain Shift press selects its row alone.
    owner.run_queue()
    assert picks(owner) == wanted and owner.tree.shown() == wanted
    assert owner.notices == []
    refresh(owner)
    assert move_to_top(owner) == wanted


def test_revalidation_between_refreshes_keeps_the_cursors_and_anchors_rows() -> None:
    """`Selection.revalidate(keep_rows=True)` drops a renamed pick and keeps a renamed cursor and
    anchor, unread; a range then starts at the anchor's row without the renamed sheet. A
    revalidation without it, as a refresh's, drops them too."""
    order = ["Alfa", "Bravo", "Charlie", "Delta", "Echo"]
    reads: list[str] = []

    class Handle:
        def __init__(self, name: str) -> None:
            self.name = name

        def getName(self) -> str:
            reads.append(self.name)
            return self.name

    tokens = {name: Handle(name) for name in order}
    selection = Selection(lambda ref: ref.token.getName() == ref.name)
    selection.choose("Bravo", tokens, order)
    selection.choose("Charlie", tokens, order, extend=True)
    assert selection.names() == ["Bravo", "Charlie"]
    tokens["Bravo"].name = tokens["Charlie"].name = "Renamed"
    reads.clear()
    assert selection.revalidate(keep_rows=True)
    assert selection.picked == [] and len(reads) == 2, "only the picks were read"
    assert isinstance(selection.cursor, Ref) and selection.cursor.name == "Charlie"
    assert isinstance(selection.anchor, Ref) and selection.anchor.name == "Bravo"
    selection.choose("Delta", tokens, order, extend=True)
    assert [ref.name for ref in selection.picked] == ["Bravo", "Charlie", "Delta"]
    assert selection.revalidate(keep_rows=True) and selection.names() == ["Delta"]
    assert selection.anchor is not None and selection.anchor.name == "Bravo"
    selection.revalidate()
    assert selection.anchor is None and selection.names() == ["Delta"]
