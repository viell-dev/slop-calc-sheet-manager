"""Pure sheet ordering. Gaps refer to the complete, original physical sheet list."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

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
            raise ValueError("Sheet names must be nonempty and unique.")
        names.add(sheet.name)
        if sheet.scenario:
            if not result:
                raise ValueError("A scenario must follow its base sheet.")
            result[-1].append(sheet.name)
        else:
            result.append([sheet.name])
    if not result:
        raise ValueError("A workbook must contain a base sheet.")
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
        raise ValueError("The selected sheets no longer exist.")
    if any(chosen.intersection(group[1:]) and group[0] not in chosen for group in groups):
        raise ValueError("Scenario sheets move only with their base sheet.")
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
            raise ValueError("The drop gap is outside the sheet list.")
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
        raise ValueError("Unknown move action.")
    return tuple(name for group in work for name in group)


def plan_order(sheets: Sequence[Sheet], target: Sequence[str]) -> Plan:
    """Plan the fewest single-sheet calls, possibly moving unselected sheets.

    A maximum-weight increasing subsequence keeps complete scenario blocks still.
    Weight is sheet count, so this also minimizes individual UNO calls. Any common
    subsequence can be extended to include the whole of each block it intersects.
    The O(B² + N²) local work avoids costly UNO calls; B <= N <= 10,000 in Calc.
    """
    groups = blocks(sheets)
    before = tuple(sheet.name for sheet in sheets)
    destination = tuple(target)
    if len(destination) != len(before) or set(destination) != set(before):
        raise ValueError("The target must contain every sheet exactly once.")
    by_name = {name: group for group in groups for name in group}
    ordered: list[tuple[str, ...]] = []
    index = 0
    while index < len(destination):
        group = by_name[destination[index]]
        if destination[index : index + len(group)] != group:
            raise ValueError("A scenario block cannot be split or reversed.")
        ordered.append(group)
        index += len(group)
    positions = {group[0]: i for i, group in enumerate(groups)}
    weights: list[int] = []
    previous: list[int] = []
    for i, group in enumerate(ordered):
        best = max(
            (j for j in range(i) if positions[ordered[j][0]] < positions[group[0]]),
            key=lambda j: weights[j],
            default=-1,
        )
        weights.append(len(group) + (weights[best] if best >= 0 else 0))
        previous.append(best)
    keep: set[str] = set()
    cursor = max(range(len(ordered)), key=lambda i: weights[i])
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
