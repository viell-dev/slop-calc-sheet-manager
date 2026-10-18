"""Pure sheet ordering. Gaps refer to the complete, original physical sheet list."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from sheet_manager.i18n import tr

Action = Literal["drop", "top", "up", "down", "bottom"]


@dataclass(frozen=True)
class Sheet:
    name: str
    scenario: bool = False


@dataclass(frozen=True)
class Move:
    name: str
    index: int  # Final zero-based index, after removing this sheet.


@dataclass(frozen=True)
class Plan:
    before: tuple[Sheet, ...]
    target: tuple[str, ...]
    moves: tuple[Move, ...]


def blocks(sheets: Sequence[Sheet]) -> tuple[tuple[str, ...], ...]:
    """Attach every scenario to the preceding base, including visible scenarios."""
    result: list[list[str]] = []
    names: set[str] = set()
    for sheet in sheets:
        if not sheet.name or sheet.name in names:
            raise ValueError(tr("Sheet names must be nonempty and unique."))
        names.add(sheet.name)
        if sheet.scenario:
            if not result:
                raise ValueError(tr("A scenario must follow its base sheet."))
            result[-1].append(sheet.name)
        else:
            result.append([sheet.name])
    if not result:
        raise ValueError(tr("A workbook must contain a base sheet."))
    return tuple(tuple(group) for group in result)


def target_order(
    sheets: Sequence[Sheet],
    selected: Iterable[str],
    action: Action,
    gap: int | None = None,
) -> tuple[str, ...]:
    """Compute an action's order; choosing a scenario alone is refused.

    Selecting a base includes its scenarios. Drops inside a scenario block snap to
    its nearest edge (ties go after it). Up/Down operate on whole blocks.
    """
    groups = blocks(sheets)
    chosen = set(selected)
    names = {sheet.name for sheet in sheets}
    if not chosen <= names:
        raise ValueError(tr("The selected sheets no longer exist."))
    if any(chosen.intersection(group[1:]) and group[0] not in chosen for group in groups):
        raise ValueError(tr("Scenario sheets move only with their base sheet."))
    selected_bases = {group[0] for group in groups if group[0] in chosen}
    work = list(groups)
    if action in ("up", "down"):
        indices = range(1, len(work)) if action == "up" else range(len(work) - 2, -1, -1)
        neighbor = -1 if action == "up" else 1
        for index in indices:
            other = index + neighbor
            if work[index][0] in selected_bases and work[other][0] not in selected_bases:
                work[index], work[other] = work[other], work[index]
    elif action in ("drop", "top", "bottom"):
        if action == "top":
            gap = 0
        elif action == "bottom":
            gap = len(sheets)
        if gap is None or not 0 <= gap <= len(sheets):
            raise ValueError(tr("The drop gap is outside the sheet list."))
        boundary = 0
        block_gap = 0
        for group in groups:
            end = boundary + len(group)
            if gap >= end or (gap > boundary and gap - boundary >= end - gap):
                block_gap += 1
            boundary = end
        moving = [group for group in groups if group[0] in selected_bases]
        remaining = [group for group in groups if group[0] not in selected_bases]
        insertion = sum(group[0] not in selected_bases for group in groups[:block_gap])
        work = remaining[:insertion] + moving + remaining[insertion:]
    else:
        raise ValueError(tr("Unknown move action."))
    return tuple(name for group in work for name in group)


def ordered_blocks(sheets: Sequence[Sheet], target: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    """Validate a target permutation and scenario ownership in O(N)."""
    groups = blocks(sheets)
    before = tuple(sheet.name for sheet in sheets)
    destination = tuple(target)
    if len(destination) != len(before) or set(destination) != set(before):
        raise ValueError(tr("The target must contain every sheet exactly once."))
    by_name = {name: group for group in groups for name in group}
    ordered: list[tuple[str, ...]] = []
    index = 0
    while index < len(destination):
        group = by_name[destination[index]]
        if destination[index : index + len(group)] != group:
            raise ValueError(tr("A scenario block cannot be split or reversed."))
        ordered.append(group)
        index += len(group)
    return tuple(ordered)


def plan_order(sheets: Sequence[Sheet], target: Sequence[str]) -> Plan:
    """Plan minimum single-sheet calls, possibly moving unselected sheets.

    Cache only the latest immutable input/result, so preflight can validate an
    externally supplied Plan without repeating planning for the usual caller.
    """
    return _plan_order(tuple(sheets), tuple(target))


@lru_cache(maxsize=1)
def _plan_order(sheets: tuple[Sheet, ...], destination: tuple[str, ...]) -> Plan:
    # A maximum-weight increasing subsequence keeps complete scenario blocks still.
    # Any common subsequence extends to the whole of each block it intersects.
    # A Fenwick prefix-maximum tree finds that subsequence in O(B log B).
    # Simulating the K actual moves with Python lists costs O(KN).
    groups = blocks(sheets)
    before = tuple(sheet.name for sheet in sheets)
    ordered = ordered_blocks(sheets, destination)
    positions = {group[0]: i for i, group in enumerate(groups)}
    tree = [(0, 0)] * (len(groups) + 1)
    previous: list[int] = []
    best_overall = (0, 0)
    for i, group in enumerate(ordered):
        position = positions[group[0]]
        best = (0, 0)
        prefix = position
        while prefix:
            best = max(best, tree[prefix])
            prefix -= prefix & -prefix
        # Negative indices preserve the earliest predecessor on equal weights.
        previous.append(-best[1] - 1)
        candidate = (best[0] + len(group), -i - 1)
        best_overall = max(best_overall, candidate)
        cursor = position + 1
        while cursor < len(tree):
            tree[cursor] = max(tree[cursor], candidate)
            cursor += cursor & -cursor
    keep: set[str] = set()
    cursor = -best_overall[1] - 1
    while cursor >= 0:
        keep.update(ordered[cursor])
        cursor = previous[cursor]
    work = list(before)
    moves: list[Move] = []
    anchor: str | None = None
    for name in reversed(destination):
        if name not in keep:
            source = work.index(name)
            following = len(work) if anchor is None else work.index(anchor)
            final_index = following - (source < following)
            if source != final_index:
                moves.append(Move(name, final_index))
                work.insert(final_index, work.pop(source))
        anchor = name
    assert tuple(work) == destination
    return Plan(tuple(sheets), destination, tuple(moves))


def plan_move(
    sheets: Sequence[Sheet], selected: Iterable[str], action: Action, gap: int | None = None
) -> Plan:
    return plan_order(sheets, target_order(sheets, selected, action, gap))
