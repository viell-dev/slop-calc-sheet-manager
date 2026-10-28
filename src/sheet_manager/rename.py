"""Renaming several sheets at once, without UNO: the editable batch, validation, and call order.

`Batch` holds the proposals the rename dialog shows: one per target, starting as its current
name, changed by editing a row or by a literal, case-sensitive Replace All. `plan_renames` turns
the changed proposals into the `setName` calls `uno_rename` makes, in an order where each call
is free when it runs.

What Calc does, measured with 26.2.1.2 and 26.8.1.1 on Linux and Windows (#102):

- `setName` refuses an empty name, one containing `: \\ / ? * [ ]`, or one that starts or ends
  with an apostrophe, silently: it returns normally and changes nothing. A NUL character is
  refused on Windows and accepted on Linux, so it is refused here. Every other name is kept
  exactly: spaces at either end or only spaces, tabs, line breaks, any length. Nothing is
  trimmed or normalized. Renaming a sheet to its own name records an undo step, so unchanged
  proposals are left out.
- Calc compares names for a rename by case folding, in the locale's rules (Turkish I and ı are
  the same letter there), and looks names up by their uppercase form. The two disagree for some
  characters: Calc accepts `ﬁ` beside `fi`, and lookup then finds `ﬁ` for both (#113). After a
  Find & Replace that ignores width, its rename comparison ignores width too (#112).

So `keys` is a conservative comparator of its own, not Calc's. Two names conflict when they share
their case folding, their uppercase form taken one character at a time, or their case folding
with I, İ and ı all read as i. That caught every conflict Calc made in the measured cases, 102 in
English locales and 14 in a Turkish one, refusals and lookup clashes alike (`test_rename.py` keeps
them). It also refuses a few pairs Calc accepts, such as ß beside ss and the I/İ/i/ı family. It
decides what the dialog accepts and the order of calls, never what Calc did: `uno_rename` reads
every call back and verifies every final name by lookup.

Only changed names are checked against the others. Pairs of unchanged names were accepted by
Calc already. A swap or a longer cycle of names passes through one temporary name per cycle, so
the number of calls is the number of changes plus the number of cycles. Temporary names are
chosen to conflict with no current, final, or other temporary name.
"""

import heapq
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sheet_manager.i18n import tr

FORBIDDEN = frozenset(":\\/?*[]")
TEMPORARY = "Sheet Manager temporary name {number}"
_MERGED_I = str.maketrans({"I": "i", "İ": "i", "ı": "i"})


def problem(name: str) -> str:
    """Why Calc would refuse this name for any sheet, or an empty string."""
    if not name:
        return tr("A sheet name cannot be empty.")
    if "\0" in name:
        return tr("A sheet name cannot contain a null character.")
    if FORBIDDEN.intersection(name):
        return tr("A sheet name cannot contain : \\ / ? * [ or ].")
    if name[0] == "'" or name[-1] == "'":
        return tr("A sheet name cannot begin or end with an apostrophe.")
    return ""


def keys(name: str) -> tuple[tuple[int, str], ...]:
    """Comparison keys: two names that share one may be the same name to Calc."""
    upper = "".join(char.upper() if len(char.upper()) == 1 else char for char in name)
    return ((0, name.casefold()), (1, upper), (2, name.translate(_MERGED_I).casefold()))


def conflict(left: str, right: str) -> bool:
    return bool(set(keys(left)) & set(keys(right)))


def visible(name: str) -> str:
    """A name with its control characters shown as their visible symbols."""
    return "".join(
        "␡" if char == "" else chr(0x2400 + ord(char)) if char < " " else char for char in name
    )


def quoted(name: str) -> str:
    """A name in a message, in quotation marks."""
    return f"“{visible(name)}”"


def shown(name: str) -> str:
    """A name in the dialog's list: quoted only if it is empty or has spaces at either end."""
    return quoted(name) if not name or name != name.strip() else visible(name)


@dataclass(frozen=True)
class Step:
    """One `setName` call: the sheet, by its name before the batch, renamed from `old` to `new`."""

    sheet: str
    old: str
    new: str


@dataclass(frozen=True)
class Plan:
    before: tuple[str, ...]  # Every sheet's name before, in document order.
    renames: tuple[tuple[str, str], ...]  # (old, new) for each changed target, in document order.
    after: tuple[str, ...]  # Every sheet's name afterwards, in document order.
    steps: tuple[Step, ...]


def problems(names: Sequence[str], renames: Iterable[tuple[str, str]]) -> dict[str, str]:
    """For each rename (old name, new name) that cannot be made, why; keyed by the old name.

    `names` is every sheet's current name. Renames to the same name are no changes and are
    never problems.
    """
    changes = {old: new for old, new in renames if new != old}
    final = [changes.get(name, name) for name in names]
    owners: dict[tuple[int, str], list[int]] = {}
    for index, name in enumerate(final):
        for key in keys(name):
            owners.setdefault(key, []).append(index)
    found: dict[str, str] = {}
    for index, old in enumerate(names):
        if old not in changes:
            continue
        new = changes[old]
        reason = problem(new)
        if not reason:
            others = sorted({other for key in keys(new) for other in owners[key] if other != index})
            same = [other for other in others if final[other] == new]
            clash = (same or others or [None])[0]
            if clash is not None:
                renamed = names[clash] in changes
                if final[clash] == new and renamed:
                    reason = tr("Another sheet would also be named {name}.")
                elif final[clash] == new:
                    reason = tr("Another sheet is already named {name}.")
                elif renamed:
                    reason = tr(
                        "Too close to {other}, another new name: Calc can treat them as one name."
                    )
                else:
                    reason = tr(
                        "Too close to {other}, another sheet's name: Calc can treat them as one "
                        "name."
                    )
                reason = reason.format(name=quoted(new), other=quoted(final[clash]))
        if reason:
            found[old] = reason
    return found


def plan_renames(names: Sequence[str], renames: Iterable[tuple[str, str]]) -> Plan:
    """The calls that give each changed sheet its new name; ValueError if any cannot be made.

    `names` is every sheet's current name, in document order; each rename is (old, new).
    """
    before = tuple(names)
    if len(set(before)) != len(before):
        raise ValueError(tr("Sheet names must be unique."))
    requested = list(renames)
    olds = [old for old, _ in requested]
    if len(set(olds)) != len(olds) or not set(olds) <= set(before):
        raise ValueError(tr("The sheets to rename no longer exist."))
    changes = {old: new for old, new in requested if new != old}
    found = problems(before, changes.items())
    if found:
        raise ValueError(next(iter(found.values())))
    after = tuple(changes.get(name, name) for name in before)
    position = {name: index for index, name in enumerate(before)}
    changed = [name for name in before if name in changes]
    # A call to a new name waits while another changed sheet still has a conflicting old name.
    # Only those waits matter: a new name conflicts with no other final name, so a finished
    # call, or a temporary name, never blocks another.
    holders: dict[tuple[int, str], set[str]] = {}
    for name in changed:
        for key in keys(name):
            holders.setdefault(key, set()).add(name)
    waiting = {
        name: {other for key in keys(changes[name]) for other in holders.get(key, ())} - {name}
        for name in changed
    }
    waiters: dict[str, set[str]] = {name: set() for name in changed}
    for name, blockers in waiting.items():
        for blocker in blockers:
            waiters[blocker].add(name)
    current = {name: name for name in changed}
    ready = [position[name] for name in changed if not waiting[name]]
    heapq.heapify(ready)
    pending = set(changed)
    used = set(before) | set(after)
    temporaries = 0
    steps: list[Step] = []

    def release(sheet: str) -> None:
        """The sheet's old name is gone: calls that waited only for it can run."""
        for waiter in waiters.pop(sheet):
            waiting[waiter].discard(sheet)
            if not waiting[waiter]:
                heapq.heappush(ready, position[waiter])

    while pending:
        if ready:
            sheet = before[heapq.heappop(ready)]
            steps.append(Step(sheet, current[sheet], changes[sheet]))
            pending.discard(sheet)
            if current[sheet] == sheet:
                release(sheet)
            continue
        # Every remaining call waits for another changed sheet's old name: follow the waits,
        # from the first such sheet, to a cycle, and give the sheet found there a temporary name.
        sheet = min(pending, key=position.__getitem__)
        seen: set[str] = set()
        while sheet not in seen:
            seen.add(sheet)
            sheet = min(waiting[sheet], key=position.__getitem__)
        temporaries += 1
        temporary = TEMPORARY.format(number=temporaries)
        while any(conflict(temporary, name) for name in used):
            temporaries += 1
            temporary = TEMPORARY.format(number=temporaries)
        used.add(temporary)
        steps.append(Step(sheet, current[sheet], temporary))
        current[sheet] = temporary
        release(sheet)
    return Plan(before, tuple((name, changes[name]) for name in changed), after, tuple(steps))


class Batch:
    """The rename dialog's proposals for its targets, in document order."""

    def __init__(self, names: Sequence[str], targets: Iterable[str]):
        self.names = tuple(names)
        chosen = set(targets)
        self.targets = tuple(name for name in self.names if name in chosen)
        self.proposals = list(self.targets)

    def set(self, index: int, name: str) -> None:
        self.proposals[index] = name

    def replace_all(self, find: str, replacement: str) -> int:
        """Replace literal, case-sensitive `find` in every proposal; the number changed."""
        if not find:
            return 0
        changed = 0
        for index, proposal in enumerate(self.proposals):
            renamed = proposal.replace(find, replacement)
            if renamed != proposal:
                self.proposals[index] = renamed
                changed += 1
        return changed

    def reset(self) -> None:
        self.proposals = list(self.targets)

    def renames(self) -> list[tuple[str, str]]:
        return list(zip(self.targets, self.proposals, strict=True))

    def changes(self) -> int:
        return sum(old != new for old, new in self.renames())

    def problems(self) -> list[str]:
        """Each row's problem, or an empty string."""
        found = problems(self.names, self.renames())
        return [found.get(old, "") for old in self.targets]

    def plan(self) -> Plan:
        return plan_renames(self.names, self.renames())


def row_label(old: str, new: str, reason: str = "") -> str:
    """A row of the dialog's list: the current name, the new one, and any problem."""
    if new == old:
        label = tr("{old}   (unchanged)").format(old=shown(old))
    else:
        label = f"{shown(old)}   →   {shown(new)}"
    return f"{label}   ⚠ {reason}" if reason else label


def summary(batch: Batch, found: Sequence[str]) -> str:
    """The dialog's status line for the whole batch."""
    wrong = sum(bool(reason) for reason in found)
    if wrong == 1:
        return tr("Correct 1 name before renaming.")
    if wrong:
        return tr("Correct {count} names before renaming.").format(count=wrong)
    changed = batch.changes()
    if not changed:
        return tr("No name has changed yet.")
    return tr("{changed} of {count} sheets will be renamed.").format(
        changed=changed, count=len(batch.targets)
    )
