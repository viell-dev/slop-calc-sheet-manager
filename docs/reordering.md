# Reordering interface

The panel uses the pure `sheet_manager.reorder` planner and the
`sheet_manager.uno_reorder` adapter. No document is saved, reloaded, copied, or closed by the
adapter. Call it synchronously on LibreOffice's UI thread. While it runs, keep the panel busy,
ignore further operation input, and defer listener-driven refresh until it returns.

```python
from sheet_manager.reorder import plan_move
from sheet_manager.uno_reorder import apply_order, preflight, snapshot

observed = snapshot(document)
plan = plan_move(observed.sheets, selected_names, "drop", gap=original_gap)
permission = preflight(context, document, observed, plan)
# Disable the control when not permission.allowed; expose permission.reason.
result = apply_order(context, document, observed, plan)
# Refresh the list and present result.message, including warnings on done.
```

`snapshot` retains sheet handles, read by index, the document identity, and a structural
monitor's generation.
Use the snapshot that produced the displayed list, rather than taking a new one to apply an old UI
selection. A rename, insertion, deletion, reorder, or scenario change invalidates it. Retained
handles are not stable sheet
identities. Measured with LibreOffice 26.2.1.2 and 26.8.1.1: a handle follows its sheet through
renames, moves, and insertions, and when its sheet is deleted it turns to the previous sheet (to
the next one when the first sheet is deleted) and follows that sheet from then on. A deleted
sheet's handle therefore reports a live name, and after a rename even its own old one. Inserting
a sheet before Bravo, deleting Bravo, and renaming the new sheet to Bravo leaves every name, every
position, and every handle's reported name as they were, although its Bravo handle now denotes
the new sheet. Names and handles alone cannot reject that snapshot.
`sheet_manager.uno_structure` supplies one monitor per document, shared by all snapshots and list
views. It attaches before the first snapshot reads sheets, lives until document disposal, and
removes itself from the cache when disposed. Closing a list view does not detach it or invalidate
other views' snapshots. It reads the sheet count and the document's undo and lock state at
every modify and undo notification, follows the save events, and moves a generation whenever a
sheet may have been inserted or deleted (`sheet_manager.structure` lists the rules). Measured
with both versions:

- Every recorded undo action is reported as it happens, before its modify notification, also
  inside `lockControllers`, `addActionLock`, `disableSetModified`, and a caller's undo context,
  and the count read then shows each step. Undoing a whole context is reported as one action.
- Modify notifications come per change, once when a `lockControllers` or `addActionLock` batch
  ends, and not at all under `disableSetModified`. Typed input reports its undo action inside an
  undo context, a modify notification, the context's end, and a second modify notification.
- With undo recording off (`IsUndoEnabled`), a change is reported only by its modify
  notification, and the undo manager then also reads as locked. Inside a lock, the one modify
  notification at the end shows recording as off if it is still off then; if recording was
  turned back on before the unlock, only the missing undo action shows the batch. While an outer
  lock is still held, nothing is reported at all, so the monitor treats a lock held at a check
  as a report that may still be coming, and the list acts on nothing until it arrives.
- A save reports several modify notifications and no undo action, all between `OnSave` and
  `OnSaveDone` (`OnSaveAs` and `OnSaveAsDone` for Save As), also for Ctrl+S and for autosave that
  saves the original document. LibreOffice can run posted work during a save, with modify
  notifications off meanwhile. Copies, PDF export, and autosave's recovery file report
  `OnCopyTo` and `OnCopyToDone` and no modification. Recalculation reports nothing; a change of
  document properties reports a modify notification without an undo action.

Threat model, decided by the maintainer: everything LibreOffice reports is caught, and a reported
change whose continuity cannot be established counts as structural. Out of scope is a structural
edit that LibreOffice does not report at all, which needs undo recording and modify
notifications both off (measured: nothing is reported then), or whose only report falls inside a
save window. The one other known way past the rules is a sequence built to report like typed
input: a recorded edit inside an undo context, then, in the same main-thread call, unrecorded
structural edits inside a lock with recording turned back on before the unlock. A program doing
either could hide or delete any sheet directly.

`is_current`, `preflight`, and `apply_order` reject a snapshot whose monitor or generation no
longer matches, even when all names, positions, and retained handle names still match
([#19](https://github.com/viell-dev/slop-calc-sheet-manager/issues/19)). Undo, Redo, and conservative
invalidation after unrecorded changes require a fresh snapshot, even if the original order has
returned. The one exception is a proved Undo or Redo of a move this adapter made, described below:
it keeps the generation, so a snapshot of either order is current again once that order is back. A held lock or unreadable safety state also refuses the operation. The adapter manages
the monitor's `own_move()` guard itself through controller unlock, so its own recorded moves do
not invalidate other list views' identity proof. Callers need no additional monitor or guard.
`preflight` is useful for enablement; `apply_order` always repeats it immediately before mutation.
Catch `ValueError` from planning and expose its reason when the selection or target is invalid.

For control enablement, `move_availability` reads the common document permissions once, and
`plan_availability` adds each plan's no-op and undo-capacity checks. These are hints, without the
full sheet scan or identity proof. Execution always calls `apply_order` with the snapshot and
selection captured for the user's request; its full preflight remains authoritative.
Enablement compares the monitor's reported `generation` without calling `check()`: a full check
consumes undo evidence that an edit's pending modify notification may still need.

`plan_move(sheets, selected, action, gap=None)` accepts `"drop"`, `"top"`, `"up"`, `"down"`, and
`"bottom"`. `target_order` computes just the target; `plan_order(sheets, target)` supports arbitrary
future reorder commands with the same validation. `Plan` includes `before`, `target`, and
`moves`; each `Move` has a sheet `name` and its final zero-based `index` after removal.

- A drop gap is `0..N` in the complete original physical order, including hidden sheets and
  scenarios. Remove the selected blocks conceptually and count remaining sheets before that gap.
  Top, Bottom, and drop gather the selected blocks in their original order.
- Up/Down move each selected run by one neighboring block; an edge-blocked run stays put.
- Each base and all following scenario sheets form a block. Selecting the base includes its
  scenarios. Selecting scenarios without their base is refused. Interior gaps snap to the nearest
  block edge, with a tie going after the block. No final target may split or reverse a block.
- A maximum-weight increasing subsequence keeps the most sheets still, preserving complete
  blocks. Other sheets move right to left before their already-positioned successors. This uses
  the fewest individual sheet moves, including when moving unselected sheets is cheaper.
  A Fenwick prefix-maximum tree finds the weighted subsequence in O(B log B), where B is the
  number of blocks. Simulating K calls costs O(KN) with Python lists. The last immutable plan is
  cached, so immediate preflight validation does not plan again; final contiguity checks are O(N).

The adapter refuses read-only documents, protected document structure, recorded changes, disabled
or locked undo, zero configured undo steps, an inactive document frame, stale state, and no-op
plans. It also refuses a plan in which a moved sheet's name would find another sheet when its call
runs: Calc accepts names that its own lookup cannot tell apart, such as `ﬁ` beside `fi`, finds
whichever comes first for both, and `moveByName` is the only move the API offers
([#113](https://github.com/viell-dev/slop-calc-sheet-manager/issues/113)). Each call checks the
name again just before it moves. Individual sheet content protection does not prevent reordering.
It groups moves with the translated `tr("Move Sheets")` title, verifies the final order and
scenario flags, and preserves the initiating view's active sheet and native tab selection.

`Result.status` is one of:

| Status | Meaning |
| --- | --- |
| `done` | The target order was verified; a view-restoration warning may accompany it. |
| `refused` | No move was attempted; `message` explains why. |
| `failed-restored` | Applying failed; the original order was verified restored; a view warning may accompany it. |
| `failed-not-restored` | Applying failed and restoration could not be verified; the user must check the document. |

`message` is translated user-facing text, `detail` is diagnostic text, and `moves` counts completed
API calls. An exception can occur after a call mutated the document, so this count is not a
rollback counter. A failure before mutation must not consume an existing user undo action.
`Availability.detail` retains safety-check exceptions; refused results propagate it. Its
`undo_steps` carries the checked capacity into execution without a second configuration read.
View-restoration errors add a translated warning and diagnostic detail without undoing a verified
move or misreporting a verified order recovery.
After verified rollback, the adapter removes the failed group's redo entry so Redo cannot replay
a partial operation. A native mutation has already discarded older redo history. Recovery never
undoes the user's preceding action. A group that received only the adapter's marker actions,
because the first move failed without changing anything, is undone and its redo entry removed the
same way; leaving that group has already discarded older redo history, so such a failure now
loses Redo history from before the move. At a full stack, Calc can still evict its oldest entry when
opening even an empty context; that native eviction does not prove that a move was recorded.

Calc reapplies the configured undo-step limit to the current context
([#16](https://github.com/viell-dev/slop-calc-sheet-manager/issues/16)), so a flat context with more
calls than that limit silently loses earlier actions. The adapter uses balanced nested contexts
when needed, keeping every level within the limit while presenting one top-level undo step.
With a one-step undo setting, multi-call plans are refused until the setting is at least two;
single-call plans remain available, without the marker actions below, which need two steps. The
adapter never changes the user's undo setting.
Preflight also refuses a move inside someone else's open undo context, because it could not be
undone independently. That check reads undo state without opening or closing any contexts.

## Undo and Redo of an own move

Undo and Redo report one action, whatever it contained, so the structure monitor moves the
generation at every Undo and Redo, and the list clears its picks. A replay of a group this
adapter recorded can only move sheets, so the adapter proves those replays instead
([#91](https://github.com/viell-dev/slop-calc-sheet-manager/issues/91)). With an undo capacity of
two or more, each group holds two marker `XUndoAction`s of the adapter's own, one before the first
move and one after the last, placed in the balanced nested contexts like the moves. They do
nothing to the document. `sheet_manager.structure` holds the rules; in short, an Undo or Redo of
the group keeps the generation only if:

- the move ended verified, and recorded exactly its moves and the two markers, at an unchanged
  generation;
- the replay's first marker (the last one for Undo, the first one for Redo) finds the group in the
  state its last transition left it, at that generation and sheet count, with no history cleared,
  no redo history cleared for Redo, and no hidden undo context entered since;
- nothing is reported between the two markers, and the undo or redo notification of the same
  direction comes next with the same count.

Measured with 26.8.1.1: each move and marker reports one undo action inside the group; Undo calls
the last marker first, with the undo manager locked and the view as it was, then the moves, the
first marker and the undo notification, and Redo the reverse; a group of moves reports nothing
else meanwhile. Undoing a group with an insertion or deletion reports modify notifications that
show the sheet count changing; actions a hidden context adds to a group are replayed outside its
markers. Turning undo recording off clears Calc's undo history, so no unrecorded change can come
between a move and its Undo. An undo title proves nothing: Calc's own move has the same one.

Anything else revokes the group for good, and its Undo and Redo invalidate as before. That
includes an Undo or Redo of anything in between, any change that moves the generation, a hidden
undo context, and a cleared history. A rollback's Undo is never proved.

After a proved replay, the adapter restores the view: at the first marker it reads each of the
document's windows' active sheet and selected tabs, as handles, and once the replay has settled it
puts back any that Calc changed, provided the generation is still the same and the document is
not locked. Calc moves the view of LibreOffice's active window, which need not be the document's
current controller, so every window is restored, not only the initiating one. The marker callbacks
run inside LibreOffice's replay, possibly on another thread: they only update the shared state,
read the count and those view getters, and post the restoration; they never raise into the
replay. Views ignore Calc's activations during a proved replay and the restoration after it, and
do not sample the tab selection until the restoration is done. Because the restoration is posted
work, that suppression is bounded: five seconds after the proof (`VIEW_RESTORE_LIMIT` in
`sheet_manager.structure`), views follow Calc's activations and sample its tabs again whether or
not the restoration has run, and a restoration that runs later leaves Calc's view as it is. The
bound trusts nothing more; it only ends the suppression.

## Limits and native semantics

An undo context groups operations; it is not a transaction. Moving a scenario block requires
individual native moves, so its intermediate physical order can be split inside the context.
The final order and rollback restore its original ownership. Do not inspect or act on intermediate
listener callbacks. If the document frame loses activation, rollback is refused rather than
pretending Calc's silent inactive-view undo restored anything.

Other document windows and native user undo/redo retain Calc's own view-selection behavior,
except that a proved Undo or Redo of an own move restores every window's view, as described above.
This adapter preserves the initiating view when applying or recovering a move; it does not replace
Calc's undo actions. Positional and 3D formulas can change values when sheet intervals change.
Direct formula, named-range, and chart-range references follow the native move and are integration
tested. Calc can replace chart object names when the chart's host sheet moves; code must not use
those names as persistent identifiers. Undo retains the new names. This native limitation also
occurs with raw `moveByName` and the native dialog, and is tracked in
[#17](https://github.com/viell-dev/slop-calc-sheet-manager/issues/17).

Translations currently fall back to English, as `sheet_manager.i18n` describes. Undo is grouped
through the same translation boundary as the rest of the extension.
