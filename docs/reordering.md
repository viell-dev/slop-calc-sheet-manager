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

`snapshot` retains sheet handles and the document identity. Use the snapshot that produced the
displayed list, rather than taking a new one to apply an old UI selection. A rename, insertion,
deletion, reorder, or scenario change invalidates it. Retained handles are not stable sheet
identities. Measured with LibreOffice 26.2.1.2 and 26.8.1.1: a handle follows its sheet through
renames, moves, and insertions, and when its sheet is deleted it turns to the previous sheet (to
the next one when the first sheet is deleted) and follows that sheet from then on. A deleted
sheet's handle therefore reports a live name, and after a rename even its own old one. Inserting
a sheet before Bravo, deleting Bravo, and renaming the new sheet to Bravo leaves every name, every
position, and every handle's reported name as they were: `is_current` accepts such a snapshot
although its Bravo handle now denotes the new sheet. Callers that keep a snapshot while the user
works must also notice insertions and deletions as they happen. `sheet_manager.uno_structure`
does that for the sheet list: it reads the sheet count and the document's undo and lock state at
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
  turned back on before the unlock, only the missing undo action shows the batch.
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
either could hide or delete any sheet directly. This layer does not use the monitor yet:
`snapshot`, `preflight`, and `apply_order` still rely on `is_current` alone, which the sequence
above passes. Wiring the generation into them is tracked in
[#19](https://github.com/viell-dev/slop-calc-sheet-manager/issues/19).
`preflight` is useful for enablement; `apply_order` always repeats it immediately before mutation.
Catch `ValueError` from planning and expose its reason when the selection or target is invalid.

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
plans. Individual sheet content protection does not prevent reordering. It groups moves with the
translated `tr("Move Sheets")` title, verifies the final order and scenario flags, and preserves
the initiating view's active sheet and native tab selection.

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
undoes the user's preceding action. At a full stack, Calc can still evict its oldest entry when
opening even an empty context; that native eviction does not prove that a move was recorded.

Calc reapplies the configured undo-step limit to the current context
([#16](https://github.com/viell-dev/slop-calc-sheet-manager/issues/16)), so a flat context with more
calls than that limit silently loses earlier actions. The adapter uses balanced nested contexts
when needed, keeping every level within the limit while presenting one top-level undo step.
With a one-step undo setting, multi-call plans are refused until the setting is at least two;
single-call plans remain available. The adapter never changes the user's undo setting.
Preflight also refuses a move inside someone else's open undo context, because it could not be
undone independently. That check reads undo state without opening or closing any contexts.

## Limits and native semantics

An undo context groups operations; it is not a transaction. Moving a scenario block requires
individual native moves, so its intermediate physical order can be split inside the context.
The final order and rollback restore its original ownership. Do not inspect or act on intermediate
listener callbacks. If the document frame loses activation, rollback is refused rather than
pretending Calc's silent inactive-view undo restored anything.

Other document windows and native user undo/redo retain Calc's own view-selection behavior.
This adapter preserves the initiating view when applying or recovering a move; it does not replace
Calc's undo actions. Positional and 3D formulas can change values when sheet intervals change.
Direct formula, named-range, and chart-range references follow the native move and are integration
tested. Calc can replace chart object names when the chart's host sheet moves; code must not use
those names as persistent identifiers. Undo retains the new names. This native limitation also
occurs with raw `moveByName` and the native dialog, and is tracked in
[#17](https://github.com/viell-dev/slop-calc-sheet-manager/issues/17).

Translations currently fall back to English, as described in the technical map. Undo is grouped
through the same translation boundary as the rest of the extension.
