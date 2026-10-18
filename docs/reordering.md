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
# Refresh the list and present result.message on refusal or failure.
```

`snapshot` retains sheet handles and the document identity. Use the snapshot that produced the
displayed list, rather than taking a new one to apply an old UI selection. A rename, insertion,
deletion, reorder, scenario change, or deletion/recreation under the same name invalidates it.
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

The adapter refuses read-only documents, protected document structure, recorded changes, disabled
or locked undo, zero configured undo steps, an inactive document frame, stale state, and no-op
plans. Individual sheet content protection does not prevent reordering. It groups moves with the
translated `tr("Move Sheets")` title, verifies the final order and scenario flags, and preserves
the initiating view's active sheet and native tab selection.

`Result.status` is one of:

| Status | Meaning |
| --- | --- |
| `done` | The target order and initiating view state were verified. |
| `refused` | No move was attempted; `message` explains why. |
| `failed-restored` | Applying failed; the original order and view state were verified restored. |
| `failed-not-restored` | Applying failed and restoration could not be verified; the user must check the document. |

`message` is translated user-facing text, `detail` is diagnostic text, and `moves` counts completed
API calls. An exception can occur after a call mutated the document, so this count is not a
rollback counter. A failure before mutation must not consume an existing user undo action.
After verified rollback, the adapter removes the failed group's redo entry so Redo cannot replay
a partial operation. A native mutation has already discarded older redo history; unrelated undo
history is retained.

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
those names as persistent identifiers. This native limitation also occurs with raw `moveByName`.

Translations currently fall back to English, as described in the technical map. Undo is grouped
through the same translation boundary as the rest of the extension.
