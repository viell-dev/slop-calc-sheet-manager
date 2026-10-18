"""Exhaustive orders and block layouts, with independent optimality/target oracles."""

from itertools import permutations

import pytest

from sheet_manager.reorder import Sheet, blocks, plan_move, plan_order, target_order


def lcs_length(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    row = [0] * (len(right) + 1)
    for name in left:
        previous = row[:]
        for j, other in enumerate(right, 1):
            row[j] = previous[j - 1] + 1 if name == other else max(previous[j], row[j - 1])
    return row[-1]


def assert_plan(sheets: tuple[Sheet, ...], target: tuple[str, ...]) -> None:
    plan = plan_order(sheets, target)
    before = tuple(sheet.name for sheet in sheets)
    work = list(before)
    for move in plan.moves:
        assert 0 <= move.index < len(work)
        source = work.index(move.name)
        assert source != move.index
        work.insert(move.index, work.pop(source))
    assert tuple(work) == target
    assert len(plan.moves) == len(before) - lcs_length(before, target)


def test_every_permutation_through_seven_sheets_is_optimal() -> None:
    # Renaming by original position covers any source order, not just alphabetic orders.
    for size in range(1, 8):
        sheets = tuple(Sheet(str(i)) for i in range(size))
        for target in permutations(sheet.name for sheet in sheets):
            assert_plan(sheets, target)


def test_every_scenario_partition_and_block_order_through_seven_sheets() -> None:
    for size in range(1, 8):
        for mask in range(1 << (size - 1)):
            sheets = tuple(
                Sheet(str(i), i > 0 and bool(mask & (1 << (i - 1)))) for i in range(size)
            )
            groups = blocks(sheets)
            for ordered in permutations(groups):
                assert_plan(sheets, tuple(name for group in ordered for name in group))


def test_every_selection_gap_and_button_through_seven_sheets() -> None:
    for size in range(1, 8):
        sheets = tuple(Sheet(str(i)) for i in range(size))
        names = tuple(sheet.name for sheet in sheets)
        for mask in range(1 << size):
            selected = {name for i, name in enumerate(names) if mask & (1 << i)}
            chosen = tuple(name for name in names if name in selected)
            remaining = tuple(name for name in names if name not in selected)
            for gap in range(size + 1):
                insertion = sum(name not in selected for name in names[:gap])
                expected = remaining[:insertion] + chosen + remaining[insertion:]
                assert target_order(sheets, selected, "drop", gap) == expected
            assert target_order(sheets, selected, "top") == chosen + remaining
            assert target_order(sheets, selected, "bottom") == remaining + chosen
            # Independent run-based oracle; every eligible run crosses one neighbor.
            for direction in ("up", "down"):
                work = list(names)
                runs: list[tuple[int, int]] = []
                i = 0
                while i < size:
                    if names[i] not in selected:
                        i += 1
                        continue
                    end = i + 1
                    while end < size and names[end] in selected:
                        end += 1
                    runs.append((i, end))
                    i = end
                for start, end in runs if direction == "up" else reversed(runs):
                    if direction == "up" and start > 0:
                        work[start - 1 : end] = names[start:end] + (names[start - 1],)
                    elif direction == "down" and end < size:
                        work[start : end + 1] = (names[end],) + names[start:end]
                target = target_order(sheets, selected, direction)
                assert target == tuple(work)
                assert_plan(sheets, target)


def test_scenarios_selection_and_drop_edges() -> None:
    sheets = (Sheet("A"), Sheet("S1", True), Sheet("S2", True), Sheet("B"), Sheet("C"))
    assert target_order(sheets, ["C"], "drop", 1) == ("C", "A", "S1", "S2", "B")
    assert target_order(sheets, ["C"], "drop", 2) == ("A", "S1", "S2", "C", "B")
    assert target_order(sheets, ["A"], "bottom") == ("B", "C", "A", "S1", "S2")
    assert target_order(sheets, ["B"], "up") == ("B", "A", "S1", "S2", "C")
    with pytest.raises(ValueError, match="only with"):
        target_order(sheets, ["S1"], "bottom")
    with pytest.raises(ValueError, match="split"):
        plan_order(sheets, ("A", "B", "S1", "S2", "C"))


def test_every_scenario_partition_selection_gap_and_button_through_seven() -> None:
    for size in range(1, 8):
        for mask in range(1 << (size - 1)):
            sheets = tuple(
                Sheet(str(i), i > 0 and bool(mask & (1 << (i - 1)))) for i in range(size)
            )
            groups = blocks(sheets)
            bases = tuple(Sheet(group[0]) for group in groups)
            boundaries = [0]
            for group in groups:
                boundaries.append(boundaries[-1] + len(group))
            by_base = {group[0]: group for group in groups}
            for selection in range(1 << len(groups)):
                selected = {group[0] for i, group in enumerate(groups) if selection & (1 << i)}
                for gap in range(size + 1):
                    edge = min(boundaries, key=lambda edge: (abs(edge - gap), -edge))
                    base_target = target_order(bases, selected, "drop", boundaries.index(edge))
                    expected = tuple(name for base in base_target for name in by_base[base])
                    target = target_order(sheets, selected, "drop", gap)
                    assert target == expected
                    assert_plan(sheets, target)
                for action in ("up", "down", "top", "bottom"):
                    base_target = target_order(bases, selected, action)
                    expected = tuple(name for base in base_target for name in by_base[base])
                    target = target_order(sheets, selected, action)
                    assert target == expected
                    assert_plan(sheets, target)


def test_large_selection_uses_one_call() -> None:
    sheets = tuple(Sheet(str(i)) for i in range(1000))
    plan = plan_move(sheets, [str(i) for i in range(999)], "bottom")
    assert [(move.name, move.index) for move in plan.moves] == [("999", 0)]


def test_invalid_inputs_and_noops() -> None:
    sheets = (Sheet("A"), Sheet("B"))
    for invalid in ((), (Sheet("A"), Sheet("A")), (Sheet("S", True),)):
        with pytest.raises(ValueError):
            blocks(invalid)
    for target in (("A",), ("A", "A"), ("A", "X")):
        with pytest.raises(ValueError):
            plan_order(sheets, target)
    with pytest.raises(ValueError):
        target_order(sheets, ["X"], "top")
    for gap in (-1, 3, None):
        with pytest.raises(ValueError):
            target_order(sheets, ["A"], "drop", gap)
    for selected in ([], ["A", "B"]):
        assert not plan_move(sheets, selected, "bottom").moves
