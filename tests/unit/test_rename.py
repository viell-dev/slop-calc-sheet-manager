"""Batch rename planning: Calc's measured naming rules, conflicts, and the order of calls."""

import random
from time import perf_counter

import pytest

from sheet_manager.rename import (
    TEMPORARY,
    Batch,
    Plan,
    conflict,
    plan_renames,
    problem,
    problems,
    row_label,
    shown,
    summary,
)

# Measured with official LibreOffice 26.2.1.2 (Linux) and 26.8.1.1 (Windows), English locales, in
# both directions (#102): "refused" means Calc's rename refused the second name beside the first;
# "lookup" that Calc accepted it although its lookup then found the first sheet for it (#113);
# "distinct" that Calc accepted it and looked both up correctly.
MEASURED = [
    ("Alpha", "ALPHA", "refused"),
    ("École", "école", "refused"),
    ("Ecole", "École", "distinct"),
    ("Å", "Å", "distinct"),
    ("é", "é", "distinct"),
    ("Straße", "STRASSE", "refused"),
    ("Straße", "strasse", "refused"),
    ("ẞ", "ß", "refused"),
    ("ẞ", "ss", "distinct"),
    ("ß", "ss", "distinct"),
    ("Σ", "ς", "refused"),
    ("σ", "ς", "refused"),
    ("İ", "i", "distinct"),
    ("I", "ı", "lookup"),
    ("I", "i", "refused"),
    ("İ", "i̇", "distinct"),
    ("I", "i̇", "distinct"),
    ("ı", "i", "lookup"),
    ("İ", "I", "distinct"),
    ("Ａ", "A", "distinct"),
    ("Ａ", "ａ", "refused"),
    ("\U0001f600North", "\U0001f600NORTH", "refused"),
    ("\U0001f600", "\U0001f601", "distinct"),
    ("ﬁ", "fi", "lookup"),
    ("ﬁ", "FI", "lookup"),
    ("K", "k", "refused"),
    ("K", "K", "refused"),
    ("Å", "å", "refused"),
    ("µ", "μ", "refused"),
    ("µ", "Μ", "refused"),
    ("ſ", "s", "refused"),
    ("ǅ", "ǆ", "refused"),
    ("ǅ", "Ǆ", "refused"),
    ("Ǆ", "ǆ", "refused"),
    ("ﬀ", "ff", "lookup"),
    ("ŉ", "ʼn", "lookup"),
    ("ΐ", "ΐ", "refused"),
    ("Ꭰ", "ꭰ", "refused"),
    ("ﬆ", "st", "lookup"),
    ("և", "եւ", "lookup"),
    ("Ა", "ა", "refused"),
    ("\U00010400", "\U00010428", "refused"),
    ("Ω", "ω", "refused"),
    ("ϐ", "β", "refused"),
    ("ϑ", "θ", "refused"),
    ("ẛ", "ṡ", "refused"),
    ("Ab C", "ab c", "refused"),
    ("A B", "A  B", "distinct"),
    ("Tab\tX", "TAB\tx", "refused"),
    ("Ì", "i̇̀", "distinct"),
    ("ì", "Ì", "refused"),
]
# The same hosts with the locale set to tr-TR before the first Calc document.
TURKISH = [
    ("I", "ı", "refused"),
    ("İ", "i", "refused"),
    ("I", "i", "distinct"),
    ("i", "ı", "distinct"),
    ("İ", "I", "distinct"),
    ("Istanbul", "istanbul", "distinct"),
    ("İstanbul", "istanbul", "refused"),
]
# Pairs Calc accepts that the comparator refuses anyway: the cost of covering every locale.
OVER_REFUSED = {
    ("ẞ", "ss"),
    ("ß", "ss"),
    ("İ", "i"),
    ("İ", "i̇"),
    ("İ", "I"),
    ("I", "i"),
    ("i", "ı"),
    ("Istanbul", "istanbul"),
}


@pytest.mark.parametrize(("left", "right", "native"), MEASURED + TURKISH)
def test_every_measured_native_conflict_is_a_conflict(left: str, right: str, native: str) -> None:
    for first, second in ((left, right), (right, left)):
        if native != "distinct":
            assert conflict(first, second), (first, second, native)
        elif (left, right) in OVER_REFUSED:
            assert conflict(first, second), "a documented conservative refusal changed"
        else:
            # Calc keeps these apart; refusing them would refuse names Calc accepts.
            assert not conflict(first, second), (first, second)


def test_fullwidth_and_halfwidth_names_stay_distinct() -> None:
    # Calc's own comparison can lose this after a Find & Replace (#112); this one must not.
    assert not conflict("Ａ", "A")
    assert not problems(["A", "Spare"], [("Spare", "Ａ")])


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("", "empty"),
        ("a\0b", "null"),
        *((f"a{char}b", "cannot contain") for char in ":\\/?*[]"),
        ("'a", "apostrophe"),
        ("a'", "apostrophe"),
        ("'", "apostrophe"),
    ],
)
def test_names_calc_refuses(name: str, reason: str) -> None:
    assert reason in problem(name)


@pytest.mark.parametrize(
    "name",
    [" ", "   ", " edge ", "a'b", "a\nb", "a\tb", "a\rb", "x\x7f", " ", "X" * 5000, "“q”"],
)
def test_names_calc_accepts_are_kept_exactly(name: str) -> None:
    assert problem(name) == ""
    plan = plan_renames(["Source", "Other"], [("Source", name)])
    assert plan.after == (name, "Other")
    assert plan.steps[0].new == name


def test_unchanged_proposals_make_no_call() -> None:
    plan = plan_renames(["Alfa", "Bravo"], [("Alfa", "Alfa"), ("Bravo", "Bravo")])
    assert plan.steps == () and plan.renames == () and plan.after == plan.before


def test_a_case_only_rename_is_one_call() -> None:
    plan = plan_renames(["north", "South"], [("north", "North")])
    assert [(s.old, s.new) for s in plan.steps] == [("north", "North")]


@pytest.mark.parametrize(
    ("renames", "expected"),
    [
        ([("Alfa", "Bravo")], "Another sheet is already named “Bravo”."),
        ([("Alfa", "BRAVO")], "Too close to “Bravo”, another sheet's name"),
        ([("Alfa", "New"), ("Charlie", "New")], "Another sheet would also be named “New”."),
        ([("Alfa", "New"), ("Charlie", "NEW")], "Too close to “NEW”, another new name"),
        ([("Alfa", "Straße"), ("Charlie", "STRASSE")], "Too close"),
        ([("Alfa", "fi"), ("Charlie", "ﬁ")], "Too close"),
        ([("Alfa", "x:y")], "cannot contain"),
    ],
)
def test_problems_name_the_conflict(renames: list[tuple[str, str]], expected: str) -> None:
    found = problems(["Alfa", "Bravo", "Charlie"], renames)
    assert expected in found[renames[0][0]], found
    with pytest.raises(ValueError):
        plan_renames(["Alfa", "Bravo", "Charlie"], renames)


def test_both_sides_of_a_conflict_are_marked() -> None:
    found = problems(["Alfa", "Bravo", "Charlie"], [("Alfa", "New"), ("Charlie", "new")])
    assert set(found) == {"Alfa", "Charlie"}


def test_unchanged_names_that_already_conflict_do_not_block_other_renames() -> None:
    # Calc accepted these already; only changed names are checked.
    plan = plan_renames(["ß", "ss", "Other"], [("Other", "Renamed")])
    assert plan.after == ("ß", "ss", "Renamed")


def test_stale_or_duplicate_targets_are_refused() -> None:
    with pytest.raises(ValueError, match="no longer exist"):
        plan_renames(["Alfa"], [("Gone", "New")])
    with pytest.raises(ValueError, match="no longer exist"):
        plan_renames(["Alfa"], [("Alfa", "One"), ("Alfa", "Two")])
    with pytest.raises(ValueError, match="unique"):
        plan_renames(["Alfa", "Alfa"], [("Alfa", "One")])


def simulate(plan: Plan) -> None:
    """Replay the calls as Calc would, refusing any call that the comparator says conflicts."""
    names = dict(zip(plan.before, plan.before, strict=True))
    temporaries: set[str] = set()
    for step in plan.steps:
        assert names[step.sheet] == step.old, step
        assert not problem(step.new), step
        for sheet, name in names.items():
            if sheet != step.sheet:
                assert not conflict(step.new, name), (step, name)
        if step.new not in plan.after:
            assert step.new.startswith(TEMPORARY.split("{")[0])
            assert all(not conflict(step.new, name) for name in plan.before + plan.after)
            temporaries.add(step.new)
        names[step.sheet] = step.new
    assert tuple(names[sheet] for sheet in plan.before) == plan.after
    assert not temporaries & set(plan.after)


@pytest.mark.parametrize(
    ("renames", "calls"),
    [
        ([("Alfa", "Bravo"), ("Bravo", "Alfa")], 3),  # A swap.
        ([("Alfa", "Bravo"), ("Bravo", "Charlie"), ("Charlie", "Alfa")], 4),  # A 3-cycle.
        ([("Alfa", "BRAVO"), ("Bravo", "alfa")], 3),  # A swap that also changes case.
        ([("Alfa", "Bravo"), ("Bravo", "Charlie"), ("Charlie", "Foxtrot")], 3),  # A chain.
        ([("Alfa", "Bravo"), ("Bravo", "Alfa"), ("Charlie", "Delta"), ("Delta", "Charlie")], 6),
        ([("Alfa", "alfa"), ("Bravo", "bravo")], 2),  # Case only: no waiting at all.
    ],
)
def test_swaps_chains_and_cycles(renames: list[tuple[str, str]], calls: int) -> None:
    plan = plan_renames(["Alfa", "Bravo", "Charlie", "Delta", "Echo"], renames)
    assert len(plan.steps) == calls, plan.steps
    simulate(plan)


def test_temporary_names_avoid_every_current_and_final_name() -> None:
    names = [TEMPORARY.format(number=1), "sheet manager TEMPORARY NAME 2", "Alfa", "Bravo"]
    plan = plan_renames(names, [("Alfa", "Bravo"), ("Bravo", "Alfa")])
    assert plan.steps[0].new == TEMPORARY.format(number=3)
    simulate(plan)


def cycles(renames: dict[str, str]) -> int:
    """Cycles of names among the renames, with case-insensitive ASCII names (an oracle)."""
    by_name = {old.casefold(): old for old in renames}
    seen: set[str] = set()
    count = 0
    for start in renames:
        path: list[str] = []
        sheet: str | None = start
        while sheet is not None and sheet not in seen:
            seen.add(sheet)
            path.append(sheet)
            target = by_name.get(renames[sheet].casefold())
            sheet = None if target == sheet else target
        if sheet is not None and sheet in path:
            count += 1
    return count


def test_random_batches_need_one_extra_call_per_cycle() -> None:
    rng = random.Random(102)
    alphabet = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]
    checked = 0
    for _ in range(3000):
        size = rng.randint(1, 8)
        names = rng.sample(alphabet, size)
        targets = rng.sample(names, rng.randint(1, size))
        pool = alphabet + [name.upper() for name in alphabet] + ["New", "Other"]
        renames = [(old, rng.choice(pool + [old])) for old in targets]
        if rng.random() < 0.5:  # A permutation of the targets' own names, often with cycles.
            shuffled = rng.sample(targets, len(targets))
            renames = [
                (old, new if rng.random() < 0.7 else new.lower())
                for old, new in zip(targets, shuffled, strict=True)
            ]
        found = problems(names, renames)
        if found:
            with pytest.raises(ValueError):
                plan_renames(names, renames)
            continue
        plan = plan_renames(names, renames)
        changes = {old: new for old, new in renames if new != old}
        simulate(plan)
        assert len(plan.steps) == len(changes) + cycles(changes), (names, renames, plan.steps)
        checked += 1
    assert checked > 1000


def test_planning_a_thousand_sheet_cycle_is_fast() -> None:
    names = [f"Tab{index:04}" for index in range(1000)]
    renames = list(zip(names, names[1:] + names[:1], strict=True))  # One cycle through every sheet.
    started = perf_counter()
    plan = plan_renames(names, renames)
    assert perf_counter() - started < 5
    assert len(plan.steps) == 1001
    chain = list(zip(names, [*names[1:], "Fresh"], strict=True))  # One chain, in the worst order.
    started = perf_counter()
    assert len(plan_renames(names, chain).steps) == 1000
    assert perf_counter() - started < 5


def test_batch_replace_all_is_literal_case_sensitive_and_cumulative() -> None:
    batch = Batch(
        ["WIP North", "Summary", "WIP South", "wip West", "WIP.x"],
        ["WIP North", "WIP South", "wip West", "WIP.x"],
    )
    assert batch.targets == ("WIP North", "WIP South", "wip West", "WIP.x")
    assert batch.replace_all("WIP ", "") == 2
    assert batch.proposals == ["North", "South", "wip West", "WIP.x"]
    assert batch.replace_all(".", "-") == 1  # Literal, not a pattern.
    assert batch.replace_all("", "x") == 0
    assert batch.replace_all("South", "S") == 1
    assert batch.proposals == ["North", "S", "wip West", "WIP-x"]
    assert batch.changes() == 3 and batch.problems() == ["", "", "", ""]
    batch.set(2, "North")
    assert batch.problems()[0] and batch.problems()[2]
    with pytest.raises(ValueError):
        batch.plan()
    batch.reset()
    assert batch.proposals == list(batch.targets) and batch.changes() == 0


def test_targets_follow_document_order() -> None:
    batch = Batch(["Alfa", "Bravo", "Charlie"], ["Charlie", "Alfa"])
    assert batch.targets == ("Alfa", "Charlie")


def test_rows_and_status_show_what_will_happen() -> None:
    assert shown("Tab\tName") == "Tab␉Name"
    assert shown(" edge") == "“ edge”" and shown("") == "“”"
    assert row_label("Old", "Old") == "Old   (unchanged)"
    assert row_label("Old", "New") == "Old   →   New"
    assert row_label("Old", "", "empty").endswith("⚠ empty")
    batch = Batch(["Alfa", "Bravo", "Charlie"], ["Alfa", "Bravo"])
    assert summary(batch, batch.problems()) == "No name has changed yet."
    batch.set(0, "One")
    assert summary(batch, batch.problems()) == "1 of 2 sheets will be renamed."
    batch.set(1, "Charlie")
    assert summary(batch, batch.problems()) == "Correct 1 name before renaming."
    batch.set(0, "")
    assert summary(batch, batch.problems()) == "Correct 2 names before renaming."
