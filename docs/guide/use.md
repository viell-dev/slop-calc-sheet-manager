# Use the sheet list

These instructions describe the `0.0.4` test build for `0.1.0`. See
[Install, update, and remove](./install.md) for setup and
[Releases and test builds](./releases.md) for available downloads.

## Open it

1. Open a workbook in Calc. The deck exists only in Calc, not in Writer or other applications.
2. Show the sidebar with **View ▸ Sidebar**. In Calc, the shortcut is Ctrl+F5.
3. Select **Sheet Manager** in the sidebar's tab bar, the column of icons along its edge.

Each full-width row is one sheet, in tab order. A square shows its tab colour; a separate arrow
in the left gutter marks the viewed sheet.
Hidden, protected, and scenario sheets have those states written beside their names. The deck is
also shown for read-only workbooks and follows the sidebar when it resizes, docks, or undocks.

## Find and select sheets

- **Click** anywhere across a row to select it without switching the viewed sheet.
- **Double-click** a visible row, or select it and press **Enter**, to go to its sheet and leave
  it as Calc's only selected tab.
- **Ctrl+click** toggles a row in the list's selection. **Shift+click** selects a range. These
  selections leave the active sheet and Calc's selected tabs unchanged.
- **Type** a sheet name's beginning to select a matching row. Repeating its first letter cycles
  through matches. Press Enter to go to the selected sheet.
- **Hidden sheets** can be selected but cannot become active. Open their menu and choose Show
  Sheet or Show Sheets to make them visible.

The list follows changes to this window's active sheet and selected Calc tabs, including tab
selection changes that leave the active sheet unchanged. While the panel is visible, it checks
the tab selection about every quarter second. Your newer input in the list takes precedence;
unchanged Calc tabs do not overwrite independent list picks.

The footer appears only when several Calc tabs are grouped. **Edits affect … Calc tabs** names
the sheets affected by cell editing, even if the list's own picks differ. Double-click a row,
press Enter on a single selected row, or click one Calc tab to end grouped editing.

Periodic tab observation pauses while the panel is collapsed, another sidebar deck is selected,
the sidebar is closed, or the window is minimized. It resumes when the panel is visible, normally
within a second. Each window on a workbook follows its own Calc selection. The list also refreshes
after renames, insertions, deletions, moves, visibility, colour, and protection changes; ordinary
cell edits do not rebuild its rows.

## Move a selection

Drag a selected row to the gap where the selected sheets should go. A line shows the insertion
point with a solid line and end markers. The selected sheets keep their relative order, even
when they started apart. Hold the
pointer near an edge to scroll, or press Esc to cancel. Dropping in place changes nothing.

Or use the **Top**, **Up**, **Down**, and **Bottom** buttons above the list, or the context menu's
**Move to top**, **Move up**, **Move down**, and **Move to bottom** actions.
Top and Bottom gather
the selected sheets, in their original order, at that end. Up and Down move each separate run of
selected sheets one place; a run already at the edge stays there. The moved sheets stay selected,
so pressing Up or Down again moves the same sheets further.

A move is one **Move Sheets** undo step. The move preserves the active sheet and Calc's tab
selection. Use Ctrl+Z to undo it. Calc's own Undo and Redo can activate an affected sheet, and the
list then follows that view; check the highlighted rows before the next move.
A stale selection or a move that cannot be fully undone is refused with
an explanation. Unavailable menu actions are disabled, with a reason in their help text, such as a
protected workbook structure, recorded changes, disabled undo, no selection, or an edge. Native
popup rendering can hide unavailable actions and their reasons; see the
[known issue](./known-issues.md).

## Open the sheet tab menu

Right-click a row to open its context menu without selecting it. If the row is already picked,
actions target the picked set; otherwise they target just that row. Menu or Shift+F10 targets the
list's picks. Opening this menu leaves the viewed sheet and Calc's selected tabs unchanged.
Move actions appear directly in it. Choose **Sheet actions…** to open Calc's full sheet-tab menu,
including your customizations. Hidden-only targets offer Show Sheet where safe.

Calc's built-in commands require its native tabs to match the context targets, so choosing
**Sheet actions…** can temporarily change Calc's tab group and viewed sheet. The list's picks
stay unchanged.
On dismissal, the previous view and group are restored where their sheet identities and visibility
can still be proved; deleting or hiding those sheets can prevent restoration. Built-in commands
keep Calc's confirmation and undo behaviour. A changed target is refused before dispatch.

**Sheet Manager Help** opens this guide. The header's native `?` uses an unavailable LibreOffice
help topic; see [Known issues](./known-issues.md).

## Keyboard

Use Tab or LibreOffice's F6 focus cycle to reach and leave the list. After a move, focus returns
to the list. While the list has focus:

| Key | Effect |
| --- | --- |
| Arrows, Home, End, Page Up, Page Down | Move through the list |
| Shift with navigation | Extend the selection |
| Ctrl with arrows, Home, or End | Move the keyboard cursor without changing the selection |
| Ctrl+Space | Toggle the cursor's row |
| Ctrl+A | Select every row |
| Letters and other printable characters | Search sheet names |
| Enter | Go to the selected visible sheet |
| Alt+Home, Up, Down, End | Move the selection to the top, up, down, or to the bottom |
| Menu or Shift+F10 | Open the sheet tab menu |
| Ctrl+S, Ctrl+Z, Ctrl+Page Down | Run Calc's save, undo, or next-sheet command |

The four move shortcuts apply only while the list or a move button has focus, without changing
Calc's shortcut configuration. In a cell, Alt+Down retains Calc's Data Select command.
Ctrl+Shift with navigation adds a range to the existing selection.

Space and Shift+Space do nothing in the list. Tab and Shift+Tab traverse the enabled move buttons
and the list, then return focus to Calc at either end. On a focused button, Enter or Space runs
that move; typing letters cannot enter cell content.
F6, F10, Esc, and unbound
Alt menu mnemonics retain LibreOffice's behaviour. Keys used by the list do not type into cells.
Other documents keep their
own keyboard handling. After Ctrl+S, focus moves to the sheet; use the focus cycle to return.

Rows use LibreOffice's native tree control and its accessible names. Hidden, protected, and
scenario states are written in text; the current-sheet arrow and tab-colour square are visual
indicators. Exposing the viewed sheet separately to assistive technology is tracked in
[#83](https://github.com/viell-dev/slop-calc-sheet-manager/issues/83). Actual screen-reader
experience is not verified by CI.

## When the list clears its selection

LibreOffice's sheet handles can change which sheet they refer to after a deletion. The list clears
its selection when it cannot establish that the picked sheets are still the same ones. This
includes inserting or deleting sheets, undo and redo, and some macro or unrecorded changes.
A notice explains conservative clearing of a user-made selection. Pick the sheets again before acting.

The list keeps its range anchor through ordinary refreshes while that sheet identity remains
valid. Large lists can take longer to refresh. See [Known issues](./known-issues.md) for
refresh costs and the limits of detecting changes made by macros.
