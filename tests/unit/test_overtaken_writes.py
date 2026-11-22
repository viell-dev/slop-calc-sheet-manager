"""Queued tree writes that meet a change the list did not make (#307, #316).

A click or a key changes the list's picks at once, and the list shows them in the tree in work
it queues. A selection made through accessibility (`XAccessibleSelection`) after that input and
before its write was overwritten by the write, and a command then acted on the input's picks:
the user's latest selection was lost without a notice (#307). The list counts the tree's changes
it did not make (#294), so the write can tell when there are changes it cannot attribute to the
input: counted after the input read the count, or seen by an input that did not claim them. It
then reads the tree, and if the tree does not show exactly the picks, it writes nothing, and the
intake takes the tree's selection, as one made without any input of the list's, deferred behind
the listeners already queued. A press handled natively after the input changes the tree too; its
listener, still queued, acts on its own change, as on `main`. When the newer change leaves the
tree showing what the list last wrote, which the intake would not see as a change, the record is
unknown instead, as after a failed write (#257): the picks go, with the selection notice.

A write of the one pick the tree already shows keeps that record, since a failure there can
leave only that pick. After a release the list accepts, the native release has selected a row
itself, so the record no longer says what the tree shows, and one failed call of the write left
that row for the intake: Move to Top moved a sheet nobody picked (#316). That write now keeps the
record only while no change the list did not make has been counted since the tree last showed
it, so the failure leaves the record unknown and the command refuses.

The real list runs over the simulated peer of `list_peer`: its tree notifies the selection
listener once per changed row; `queued_click` queues a click's listeners behind the work already
posted, as VCL does (#269); `release` selects the row under the pointer, and a test that models
VCL's release at the press's position selects that row itself. The failures are injected; no
native trigger is known (#257).
"""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.list_peer import (
    DOWN,
    LEFT,
    MOD1,
    SHIFT,
    SPACE,
    UP,
    A,
    Book,
    click,
    key,
    listen,
    move_to_top,
    picks,
    press,
    queued_click,
    record_activations,
    release,
    sheet_list,
)

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]


def row(name: str) -> int:
    return NAMES.index(name)


def fresh() -> Any:
    return sheet_list(Book(list(NAMES)))


def run(owner: Any, count: int) -> None:
    """Run the next `count` items of the queue, as LibreOffice would next."""
    for _ in range(count):
        work, _where = owner.queue.pop(0)
        work()


def sample(owner: Any) -> None:
    """The tab observer's timer's sample, whose deferred intake is posted."""
    owner._take_tree_selection(paint=False, defer=True, tick=True)


def only(name: str) -> Callable[[Any], None]:
    def select(owner: Any) -> None:
        owner.tree.assistive_only(name)

    return select


def add(name: str) -> Callable[[Any], None]:
    def select(owner: Any) -> None:
        owner.tree.assistive_select(name)

    return select


def clear(owner: Any) -> None:
    owner.tree.assistive_clear()


def reselect(name: str) -> Callable[[Any], None]:
    """Deselect a row and select it again through accessibility: two changes, none left."""

    def select(owner: Any) -> None:
        others = [node for node in owner.tree.selected if node.DataValue != name]
        owner.tree.selected = others
        owner.tree.selected = [*others, owner.tree.node(name)]

    return select


def refused(owner: Any, notices: int) -> None:
    """The list dropped the picks with the notice, cleared the tree, and Move to Top refuses."""
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


def taken(owner: Any, names: list[str], notices: int) -> None:
    """The list took the tree's selection, `names`, with no notice, and Move to Top moves it, or
    refuses when it is empty."""
    assert picks(owner) == names == owner.tree.shown()
    assert len(owner.notices) == notices
    assert move_to_top(owner) == (names or None)


# An assistive selection between a key and its write (#307, the first row).

# Each change and the rows the tree shows after it.
ASSISTIVE: dict[str, tuple[Callable[[Any], None], list[str]]] = {
    "Echo alone": (only("Echo"), ["Echo"]),
    "Echo added": (add("Echo"), ["Alfa", "Echo"]),
    "cleared": (clear, []),
}
KEYS = {"Down": (DOWN, 0), "Shift+Down": (DOWN, SHIFT), "Ctrl+A": (A, MOD1)}
# Every key and change but Ctrl+A with Echo added, which Ctrl+A's picks already include: that
# is a cost (`test_an_assistive_change_the_picks_include_replaces_them`).
OVERWRITTEN = [
    pytest.param(*KEYS[keys], *ASSISTIVE[change], id=f"{keys}-{change}")
    for keys in KEYS
    for change in ASSISTIVE
    if (keys, change) != ("Ctrl+A", "Echo added")
]


@pytest.mark.parametrize("code, modifiers, assistive, tree", OVERWRITTEN)
def test_a_keys_write_does_not_show_its_picks_over_a_newer_assistive_selection(
    code: int, modifiers: int, assistive: Callable[[Any], None], tree: list[str]
) -> None:
    """Alfa picked; a key changes the picks and queues its write; the tree's selection is then
    changed through accessibility before that write runs. The write showed the key's picks over
    it, and Move to Top moved them. Now the write finds changes counted after the key and a tree
    that does not show the picks, so it writes nothing, and the intake takes the tree's
    selection: the user's latest selection is not replaced by an older one."""
    owner = fresh()
    click(owner, row("Alfa"))
    notices = len(owner.notices)
    owner.tree_key(code, modifiers)
    assistive(owner)
    owner.run_queue()
    taken(owner, tree, notices)


@pytest.mark.parametrize("code, modifiers", list(KEYS.values()), ids=list(KEYS))
def test_a_newer_change_back_to_the_shown_selection_drops_the_keys_picks(
    code: int, modifiers: int
) -> None:
    """As above, with Alfa deselected and selected again through accessibility: the tree shows
    Alfa, which the list last wrote, so the intake would see no change and the picks would stay
    the key's, which the tree does not show. The record is unknown instead, and the picks go,
    with the notice."""
    owner = fresh()
    click(owner, row("Alfa"))
    notices = len(owner.notices)
    owner.tree_key(code, modifiers)
    reselect("Alfa")(owner)
    owner.run_queue()
    refused(owner, notices)


@pytest.mark.parametrize(
    "assistive",
    [
        pytest.param(only("Echo"), id="Echo alone"),
        pytest.param(add("Echo"), id="Echo added"),
        pytest.param(clear, id="cleared"),
    ],
)
def test_a_ctrl_keys_write_does_not_show_the_picks_over_a_newer_assistive_selection(
    assistive: Callable[[Any], None],
) -> None:
    """Ctrl+Down keeps the picks and moves the cursor; its write showed Alfa again over the
    selection made after it, and Move to Top moved Alfa. The intake now takes the tree's."""
    owner = fresh()
    click(owner, row("Alfa"))
    owner.tree_key(DOWN, MOD1)
    assistive(owner)
    shown = owner.tree.shown()
    owner.run_queue()
    taken(owner, shown, 0)


def test_an_assistive_change_the_picks_include_replaces_them() -> None:
    """The cost of the rule: Ctrl+A picks every sheet, and Echo is added through accessibility
    before its write. Showing every sheet would undo nothing the user did, as on `main`, but the
    write cannot tell which rows the change selected, only that the tree does not show the picks,
    so the intake takes what the tree shows, Alfa and Echo."""
    owner = fresh()
    click(owner, row("Alfa"))
    owner.tree_key(A, MOD1)
    owner.tree.assistive_select("Echo")
    owner.run_queue()
    taken(owner, ["Alfa", "Echo"], 0)


def test_a_ctrl_keys_write_goes_ahead_when_the_newer_change_leaves_the_picks_shown() -> None:
    """Control: after Ctrl+Down, Alfa is deselected and selected again through accessibility.
    The tree shows exactly the picks, so the write overwrites nothing and goes ahead."""
    owner = fresh()
    click(owner, row("Alfa"))
    notices = len(owner.notices)
    owner.tree_key(DOWN, MOD1)
    reselect("Alfa")(owner)
    owner.run_queue()
    assert picks(owner) == ["Alfa"] == owner.tree.shown() and len(owner.notices) == notices
    assert move_to_top(owner) == ["Alfa"]


@pytest.mark.parametrize("sampled", [False, True], ids=["no sample", "sampled"])
def test_the_tab_sample_before_the_write_changes_nothing(sampled: bool) -> None:
    """As the first row, with the tab sample between the assistive selection and the write: its
    deferred intake runs after the write, finds the key's input, and takes nothing; the write's
    own intake then takes Echo."""
    owner = fresh()
    click(owner, row("Alfa"))
    owner.tree_key(DOWN, 0)
    owner.tree.assistive_only("Echo")
    if sampled:
        sample(owner)
    owner.run_queue()
    taken(owner, ["Echo"], 0)


# An assistive selection between a press's native handling and its listener (#307's rows 2, 3).


@pytest.mark.parametrize(
    "assistive",
    [
        pytest.param(only("Echo"), id="Echo alone"),
        pytest.param(add("Echo"), id="Echo added"),
        pytest.param(clear, id="cleared"),
    ],
)
def test_a_clicks_write_does_not_show_its_pick_over_a_newer_assistive_selection(
    assistive: Callable[[Any], None],
) -> None:
    """Alfa picked; a click on Charlie is handled natively, and the selection changes through
    accessibility before the click's listeners run. The listener picked Charlie and its write
    showed Charlie over the selection, for Move to Top to move. The listener now finds changes
    beyond its press's own share, and the write, finding the tree showing something else than
    Charlie, writes nothing; the intake takes what the tree shows."""
    owner = fresh()
    click(owner, row("Alfa"))
    queued_click(owner, row("Charlie"), 0)
    assistive(owner)
    shown = owner.tree.shown()
    owner.run_queue()
    taken(owner, shown, 0)


def test_a_ctrl_shift_range_behind_a_refusal_is_not_shown_over_a_newer_selection() -> None:
    """#307's third row. Bravo picked; a Ctrl+click on Bravo and a Ctrl+Shift+click on Delta
    are handled natively, then Hotel is selected alone through accessibility, all before the
    first listener. The Ctrl+click's listener is refused and accounts for every change counted,
    so the Ctrl+Shift+click's listener found nothing unaccounted and added its range to the
    emptied picks: Move to Top moved Bravo to Delta, though the tree last showed Hotel alone. The
    refusal records that it saw changes besides its own, and the range's write, finding the tree
    showing Hotel, writes nothing. The tree may still show the refused toggle's own native change,
    which the list could not interpret, so the record is unknown rather than taken: the picks go,
    with the notice."""
    owner = fresh()
    click(owner, row("Bravo"))
    notices = len(owner.notices)
    queued_click(owner, row("Bravo"), MOD1)
    queued_click(owner, row("Delta"), MOD1 | SHIFT)
    owner.tree.assistive_only("Hotel")
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) > notices
    assert move_to_top(owner) is None


def test_a_refused_toggles_native_change_is_not_taken() -> None:
    """Without assistive technology: a Ctrl+double-click on Foxtrot, a Ctrl+click on Bravo and a
    Ctrl+Shift+click on Alfa, all handled before the first listener. The first listener is
    refused, since the others' changes are counted with its own, and the range's write finds the
    tree showing Foxtrot, which that refused toggle selected natively. Taking the tree would pick
    Foxtrot, which the list's own reading of the double click toggles off; the picks go instead,
    with the notice, where `main` moves Alfa and Bravo (a cost)."""
    owner = fresh()
    notices = len(owner.notices)
    queued_click(owner, row("Foxtrot"))
    queued_click(owner, row("Foxtrot"), clicks=2)
    queued_click(owner, row("Bravo"))
    queued_click(owner, row("Alfa"), MOD1 | SHIFT)
    owner.run_queue()
    assert "Foxtrot" not in picks(owner)
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) > notices
    assert move_to_top(owner) is None


def failed_down(owner: Any) -> None:
    """Down, whose write fails at its `select`: the record is unknown, as after any failed write
    (#257), and the tree still shows Alfa."""
    owner.faults.fail("select")
    owner.tree_key(DOWN, 0)
    owner.run_queue()
    assert owner.faults.failed == ["select"] and owner._shown is None


@pytest.mark.parametrize("unknown", [False, True], ids=["record known", "record unknown"])
def test_a_click_released_over_another_row_does_not_show_its_pick_over_a_newer_selection(
    unknown: bool,
) -> None:
    """Alfa picked, and if `unknown`, a failed write of Down first. The click on Charlie is
    handled natively, Echo is selected alone through accessibility, and the button goes up over
    Delta, where VCL's release changes nothing for a press on a row it did not show selected. The
    release does not narrow the picks, so only the press's listener can tell that changes besides
    its own came before it: beyond its share, or any change at all while the record is unknown.
    Its write ran while the button was held and showed Charlie over Echo. It now writes nothing:
    the intake takes Echo, or, with the record unknown, drops the picks with the notice."""
    owner = fresh()
    click(owner, row("Alfa"))
    if unknown:
        failed_down(owner)
    notices = len(owner.notices)
    pressed = owner.tree._installed()[row("Charlie")]
    owner.tree.selected, owner.tree.cursor = [pressed], pressed
    owner.tree.assistive_only("Echo")
    line = owner.tree.line(row("Charlie"))
    down = SimpleNamespace(Buttons=LEFT, X=0, Y=line, Modifiers=0, ClickCount=1)
    owner.post(lambda: listen(owner, owner.mouse_pressed, down), "a mouse press")
    owner.run_queue()
    up = SimpleNamespace(
        Buttons=LEFT, X=0, Y=owner.tree.line(row("Delta")), Modifiers=0, ClickCount=1
    )
    listen(owner, owner.mouse_released, up)
    owner.run_queue()
    if unknown:
        refused(owner, notices)
    else:
        taken(owner, ["Echo"], notices)


def narrowing_release(owner: Any, name: str, assistive: Callable[[Any], None] | None) -> None:
    """Alfa and Charlie picked; `name` pressed and held, its listener run; the release in its row,
    which VCL's selection engine handles by selecting the pressed row alone, then `assistive`, if
    given, before the release's listener."""
    queued_click(owner, row("Charlie"))
    owner.run_queue()
    press(owner, row(name))
    owner.run_queue()
    pressed = owner.tree._installed()[row(name)]
    owner.tree.selected, owner.tree.cursor = [pressed], pressed
    if assistive is not None:
        assistive(owner)
    line = owner.tree.line(row(name))
    event = SimpleNamespace(Buttons=LEFT, X=0, Y=line, Modifiers=0, ClickCount=1)
    listen(owner, owner.mouse_released, event)
    owner.run_queue()


def test_a_click_on_a_picked_row_does_not_show_its_pick_over_a_newer_selection() -> None:
    """A click on Charlie, already picked: the tree narrows the selection to Charlie when the
    button goes up, and Echo is added through accessibility before the release's listener. The
    listener narrowed the picks to Charlie and its write showed Charlie over Echo. The release
    now finds changes it does not claim, and the write, finding Echo too, writes nothing: the
    intake takes Charlie and Echo, as the tree shows them."""
    owner = fresh()
    click(owner, row("Alfa"))
    narrowing_release(owner, "Charlie", add("Echo"))
    taken(owner, ["Charlie", "Echo"], 0)


def test_a_click_on_a_picked_row_narrows_the_picks() -> None:
    """Control: the same click without the assistive change narrows the picks to Charlie."""
    owner = fresh()
    click(owner, row("Alfa"))
    narrowing_release(owner, "Charlie", None)
    assert picks(owner) == ["Charlie"] == owner.tree.shown() and owner.notices == []
    assert move_to_top(owner) == ["Charlie"]


def test_a_plain_press_on_an_unknown_record_claims_nothing() -> None:
    """Down's write failed, so the record is unknown; a click on Charlie is handled natively and
    Echo is selected through accessibility before its listeners. With the record unknown, the
    plain press has no share to count, so it claims none of the changes, and its write, finding
    Echo where it would show Charlie, writes nothing; the intake settles the record and drops the
    picks, with the notice."""
    owner = fresh()
    click(owner, row("Alfa"))
    failed_down(owner)
    notices = len(owner.notices)
    queued_click(owner, row("Charlie"), 0)
    owner.tree.assistive_only("Echo")
    owner.run_queue()
    refused(owner, notices)


# Controls: input in order, and presses whose listeners follow their own native change.


def test_inputs_in_order_act_as_before() -> None:
    """A click, a key and an assistive selection, each after the last has been shown: each one
    acts, and no notice is shown."""
    owner = fresh()
    click(owner, row("Alfa"))
    assert move_to_top(owner) == ["Alfa"]
    key(owner, DOWN)
    assert picks(owner) == ["Bravo"] == owner.tree.shown()
    owner.tree.assistive_only("Echo")
    sample(owner)
    owner.run_queue()
    assert picks(owner) == ["Echo"] and move_to_top(owner) == ["Echo"]
    assert owner.notices == []


def test_a_key_after_an_assistive_selection_acts_on_its_own_picks() -> None:
    """Echo selected through accessibility, then Down before any intake: the key is the newer
    input, so its write shows Bravo over Echo, as on `main`."""
    owner = fresh()
    click(owner, row("Alfa"))
    owner.tree.assistive_only("Echo")
    key(owner, DOWN)
    assert picks(owner) == ["Bravo"] == owner.tree.shown() and owner.notices == []
    assert move_to_top(owner) == ["Bravo"]


def test_a_click_after_an_assistive_selection_acts_on_its_own_row() -> None:
    """Echo selected through accessibility, then a click on Charlie handled natively, which
    deselects Echo, before its listeners: the listener finds Echo's changes beyond its share, but
    the tree shows exactly Charlie, so its write goes ahead."""
    owner = fresh()
    click(owner, row("Alfa"))
    owner.tree.assistive_only("Echo")
    queued_click(owner, row("Charlie"), 0)
    owner.run_queue()
    assert picks(owner) == ["Charlie"] == owner.tree.shown() and owner.notices == []
    assert move_to_top(owner) == ["Charlie"]


def test_a_click_handled_after_a_key_acts_on_its_row() -> None:
    """Down, then a click on Charlie handled natively before the key's write. The click came
    last: the key's write leaves the tree as the click left it, and the click picks Charlie,
    with no notice, as on `main`."""
    owner = fresh()
    click(owner, row("Alfa"))
    owner.tree_key(DOWN, 0)
    queued_click(owner, row("Charlie"), 0)
    owner.run_queue()
    assert picks(owner) == ["Charlie"] == owner.tree.shown() and owner.notices == []
    assert move_to_top(owner) == ["Charlie"]


def test_a_ctrl_click_between_a_plain_click_and_its_write_toggles_its_row() -> None:
    """#44's order: VCL runs a plain click's listeners before it handles a Ctrl+click on Echo,
    and the plain click's write comes between the Ctrl+click and its listener. That write leaves
    Echo's toggle in the tree, unaccounted, and the Ctrl+click's listener takes it for its own:
    Charlie and Echo are picked, as on `main`, with no notice."""
    owner = fresh()
    click(owner, row("Alfa"))
    queued_click(owner, row("Charlie"), 0)
    run(owner, 2)  # The plain click's listeners; their write stays queued.
    queued_click(owner, row("Echo"))
    owner.run_queue()
    assert picks(owner) == ["Charlie", "Echo"] == owner.tree.shown() and owner.notices == []
    assert move_to_top(owner) == ["Charlie", "Echo"]


def test_two_quick_clicks_pick_the_second() -> None:
    """Two plain clicks handled natively before the first one's listeners: the first listener
    finds the second click's changes beyond its share, its write leaves the tree to the second,
    and the second click picks its row, with no notice."""
    owner = fresh()
    click(owner, row("Alfa"))
    queued_click(owner, row("Charlie"), 0)
    queued_click(owner, row("Echo"), 0)
    owner.run_queue()
    assert picks(owner) == ["Echo"] == owner.tree.shown() and owner.notices == []
    assert move_to_top(owner) == ["Echo"]


def test_a_ctrl_double_click_after_a_plain_click_toggles_twice() -> None:
    """A click on Delta and a Ctrl+double-click on Charlie, all handled before the first
    listener. The plain press's listener finds Charlie's toggle beyond its share; Charlie's first
    listener then claims it as its own, and its second toggles Charlie off again, with no native
    change. The write shows Delta, as on `main`: a mark left after Charlie's claim made the write
    find the tree showing Charlie and leave it to the intake, which picked Charlie."""
    owner = fresh()
    queued_click(owner, row("Delta"), 0)
    queued_click(owner, row("Charlie"))
    queued_click(owner, row("Charlie"), clicks=2)
    owner.run_queue()
    assert picks(owner) == ["Delta"] == owner.tree.shown() and owner.notices == []
    assert move_to_top(owner) == ["Delta"]


def test_two_quick_ctrl_clicks_toggle_both_rows() -> None:
    """Bravo picked; a Ctrl+click on Charlie whose listeners run before a Ctrl+click on Delta is
    handled, and whose write runs between that press and its listener: both rows are added."""
    owner = fresh()
    click(owner, row("Bravo"))
    queued_click(owner, row("Charlie"))
    run(owner, 2)
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Charlie", "Delta"] == owner.tree.shown()
    assert owner.notices == []


def test_a_ctrl_click_after_a_plain_clicks_write_was_left_and_a_refresh_still_toggles() -> None:
    """#44's real-input check with a delayed refresh (`check_stale_clicks`): a double click on
    Bravo, whose listeners run before VCL handles a Ctrl+click on Delta, and a refresh queued for
    another window's colour change that runs after the double click's write and before the
    Ctrl+click's listener. The write leaves Delta's toggle in the tree; the refresh's intake
    defers it, as the tab sample's does, so the Ctrl+click's listener runs first and toggles
    Delta: Bravo and Delta are picked, as on `main`. A record left unknown there instead was
    settled by the refresh, which dropped Bravo, and the held listener picked nothing."""
    owner = fresh()
    record_activations(owner)
    click(owner, row("Alfa"))
    queued_click(owner, row("Bravo"), 0)
    queued_click(owner, row("Bravo"), 0, clicks=2)
    while owner.queue and owner.queue[0][1].startswith("a mouse"):
        run(owner, 1)  # The double click's listeners; their write and activation stay queued.
    owner.book.sheet("Foxtrot").color = 0x2A6099
    queued_click(owner, row("Delta"))
    listeners = [item for item in owner.queue if item[1].startswith("a mouse")]
    owner.queue[:] = [item for item in owner.queue if not item[1].startswith("a mouse")]
    owner.post(owner.refresh, "refreshing the sheet list")
    owner.queue.extend(listeners)
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Delta"] == owner.tree.shown() and owner.notices == []
    assert move_to_top(owner) == ["Bravo", "Delta"]


def test_a_ctrl_click_handled_after_a_key_is_still_held() -> None:
    """Down, then a Ctrl+click on Echo handled natively before the key's write: the key's hold
    refuses the toggle, as on `main`; the write it would have shown is left to the intake."""
    owner = fresh()
    click(owner, row("Alfa"))
    notices = len(owner.notices)
    owner.tree_key(DOWN, 0)
    queued_click(owner, row("Echo"))
    owner.run_queue()
    refused(owner, notices)


def test_a_right_press_over_a_newer_assistive_selection_targets_its_row_alone() -> None:
    """Alfa and Echo picked; a right press on Echo, and Golf selected alone through accessibility
    before its write. The write showed Alfa and Echo again, and the menu targeted both. It now
    writes nothing and leaves the record unknown, since the record still matches the picks, and
    the menu its release opens targets Echo alone; the intake then drops the picks with the
    notice."""
    owner = fresh()
    click(owner, row("Alfa"))
    queued_click(owner, row("Echo"))
    owner.run_queue()
    opened: list[list[str]] = []

    def open_menu(x: int, y: int, refs: Any = None, seen: int | None = None) -> None:
        # As `_open_menu` chooses its targets for a right press (#307).
        target, names = owner._context_target, picks(owner)
        shown = owner._shown is not None and set(owner._shown) == set(names)
        opened.append(names if shown and target.name in names else [target.name])
        owner._context_target = None

    owner._open_menu = open_menu
    queued_click(owner, row("Echo"), 0, button=2)
    run(owner, 1)  # The press's listener; its write and the release's listener are queued.
    owner.tree.assistive_only("Golf")
    owner.run_queue()
    assert opened == [["Echo"]]
    owner._take_tree_selection()
    owner.run_queue()
    assert picks(owner) == [] and move_to_top(owner) is None


# A failed write after an accepted held click (#316).


def held_foxtrot_released_over_bravo(owner: Any, call: str | None = None) -> None:
    """Foxtrot, the one pick, pressed again and released over Bravo, which the simulated tree's
    native release selects; the list accepts the release and queues its write, whose `call`
    fails once if given."""
    press(owner, row("Foxtrot"))
    owner.run_queue()
    if call is not None:
        owner.faults.fail(call)
    release(owner, row("Bravo"))


@pytest.mark.parametrize(
    "call, moved",
    [
        pytest.param("getModel", None, id="getModel"),
        pytest.param("SelectionType", None, id="SelectionType"),
        pytest.param("select", None, id="select"),
        pytest.param("select cleared", None, id="select after clearing"),
        pytest.param("select done", ["Foxtrot"], id="select after selecting"),
    ],
)
def test_a_failed_write_after_an_accepted_release_leaves_the_released_row_to_no_one(
    call: str, moved: list[str] | None
) -> None:
    """The write that an accepted release queues repeats the `select` of the one pick, Foxtrot,
    and kept the record that the tree shows Foxtrot because a failure there could leave only
    that pick. The native release had selected Bravo, so when the write failed before its
    `select` took effect, the intake took Bravo, and Move to Top moved it, though nobody picked
    it. The record is now unknown from the write's first call, since the release's change was
    counted: Move to Top refuses, with the notice, or moves Foxtrot when the tree shows it."""
    owner = fresh()
    click(owner, row("Foxtrot"))
    notices = len(owner.notices)
    held_foxtrot_released_over_bravo(owner, call)
    owner.run_queue()
    assert owner.faults.failed == [call]
    assert move_to_top(owner) == moved
    assert len(owner.notices) == notices + (moved is None)
    owner.retry()
    assert move_to_top(owner) in (None, ["Foxtrot"]), "Bravo, which nobody picked, was moved"


def test_a_failed_write_after_keys_during_the_hold_leaves_the_pressed_row_to_no_one() -> None:
    """VCL's release selects the pressed row, Foxtrot, rather than the one under the pointer.
    Ctrl+A and Down during the hold pick Golf alone, and the release over Bravo is accepted; its
    write repeats Golf's `select` and fails at its first call. The intake took Foxtrot, which
    the user replaced with Golf, and Move to Top moved it. Now it refuses."""
    owner = fresh()
    click(owner, row("Foxtrot"))
    press(owner, row("Foxtrot"))
    owner.run_queue()
    key(owner, A, MOD1)
    key(owner, DOWN)
    assert picks(owner) == ["Golf"] == owner.tree.shown()
    owner.faults.fail("getModel")
    pressed = owner.tree._installed()[row("Foxtrot")]
    owner.tree.selected, owner.tree.cursor = [pressed], pressed
    event = SimpleNamespace(
        Buttons=LEFT, X=0, Y=owner.tree.line(row("Bravo")), Modifiers=0, ClickCount=1
    )
    listen(owner, owner.mouse_released, event)
    owner.run_queue()
    assert owner.faults.failed == ["getModel"]
    assert move_to_top(owner) is None


def test_an_accepted_release_over_another_row_still_shows_its_pick() -> None:
    """Control: with no failure, the write shows Foxtrot, and Move to Top moves it."""
    owner = fresh()
    click(owner, row("Foxtrot"))
    held_foxtrot_released_over_bravo(owner)
    owner.run_queue()
    assert picks(owner) == ["Foxtrot"] == owner.tree.shown() and owner.notices == []
    assert move_to_top(owner) == ["Foxtrot"]


def test_a_failed_repeat_with_nothing_else_counted_keeps_the_record() -> None:
    """Control: Foxtrot pressed again and released in its own row, where the native release
    changes nothing. With nothing counted since the tree showed Foxtrot, the write keeps the
    record, so a failure at its first call leaves Foxtrot shown and picked, as before."""
    owner = fresh()
    click(owner, row("Foxtrot"))
    press(owner, row("Foxtrot"))
    owner.run_queue()
    owner.faults.fail("getModel")
    release(owner, row("Foxtrot"))
    owner.run_queue()
    assert owner.faults.failed == ["getModel"]
    assert owner._shown == ("Foxtrot",)
    assert move_to_top(owner) == ["Foxtrot"] and owner.notices == []


def test_space_after_an_overtaken_write_is_refused() -> None:
    """After the write left Echo in the tree, Ctrl+Space, before the intake, toggles nothing:
    the tree shows Echo, which the picks lack, as after any change the list has not taken."""
    owner = fresh()
    click(owner, row("Alfa"))
    owner.tree_key(DOWN, 0)
    owner.tree.assistive_only("Echo")
    run(owner, 1)  # The key's write, which leaves the tree as it is.
    assert owner._shown == ("Alfa",) and owner.tree.shown() == ["Echo"]
    owner.tree_key(UP, MOD1)
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert picks(owner) == [] and move_to_top(owner) is None
