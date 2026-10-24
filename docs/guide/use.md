# Use the sheet list

**Unreleased:** these instructions describe the development version. There is no published build
yet. See [Install, update, and remove](./install.md) to build it yourself.

## Open it

1. Open a workbook in Calc. The deck exists only in Calc, not in Writer or other applications.
2. Show the sidebar with **View ▸ Sidebar**. In Calc, the shortcut is Ctrl+F5.
3. Select **Sheet Manager** in the sidebar's tab bar, the column of icons along its edge.

Each row is one sheet, in tab order. A square shows its tab colour; `▸` marks the active sheet.
Hidden, protected, and scenario sheets have those states written beside their names. The deck is
also shown for read-only workbooks and follows the sidebar when it resizes, docks, or undocks.

## Find and select sheets

- **Click** a visible row to go to its sheet and leave it as Calc's only selected tab.
- **Ctrl+click** toggles a row in the list's selection. **Shift+click** selects a range. These
  selections leave the active sheet and Calc's selected tabs unchanged.
- **Type** a sheet name's beginning to select a matching row. Repeating its first letter cycles
  through matches. Press Enter to go to the selected sheet.
- **Hidden sheets** can be selected but cannot become active. Open their menu and choose Show
  Sheet or Show Sheets to make them visible.

The list follows Calc's selection when the active sheet changes. Selecting tabs without switching
the active sheet reaches the list at the next sheet switch. The list refreshes after renames,
insertions, deletions, moves, visibility, colour, and protection changes.

## Move a selection

Drag a selected row to the gap where the selected sheets should go. A line shows the insertion
point. The selected sheets keep their relative order, even when they started apart. Hold the
pointer near an edge to scroll, or press Esc to cancel. Dropping in place changes nothing.

A move is one **Move Sheets** undo step. Use Ctrl+Z to undo it. The active sheet and Calc's tab
selection are preserved. A stale selection or a move that cannot be fully undone is refused with
an explanation. Movement buttons are planned but not implemented yet.

## Open the sheet tab menu

Right-click a row, press the Menu key, or press Shift+F10. The menu is Calc's sheet tab menu,
including your customizations, acting on the sheets selected in the list. When Calc cannot select
exactly those sheets, a short menu offers Show Sheet where that is safe.

**Opening the native menu groups Calc's tabs. Cell edits then affect every grouped sheet.** Click
one row or one sheet tab before editing a single sheet. Built-in commands retain Calc's own
confirmation and undo behaviour. The menu refuses a command if its target sheets change while
it is open.

## Keyboard

Use Tab or LibreOffice's F6 focus cycle to reach and leave the list. While it has focus:

| Key | Effect |
| --- | --- |
| Arrows, Home, End, Page Up, Page Down | Move through the list |
| Shift with navigation | Extend the selection |
| Ctrl with arrows, Home, or End | Move the keyboard cursor without changing the selection |
| Ctrl+Space | Toggle the cursor's row |
| Ctrl+A | Select every row |
| Letters and other printable characters | Search sheet names |
| Enter | Go to the selected visible sheet |
| Menu or Shift+F10 | Open the sheet tab menu |
| Ctrl+S, Ctrl+Z, Ctrl+Page Down | Run Calc's save, undo, or next-sheet command |

Space and Shift+Space do nothing. Tab, F6, F10, Esc, and unbound Alt menu mnemonics retain
LibreOffice's behaviour. Keys used by the list do not type into cells. Other documents keep their
own keyboard handling. After Ctrl+S, focus moves to the sheet; use the focus cycle to return.

Rows use LibreOffice's native tree control and its accessible names. States are written in text
as well as shown by colour or position; actual screen-reader experience is not verified by CI.

## When the list clears its selection

LibreOffice's sheet handles can change which sheet they refer to after a deletion. The list clears
its selection when it cannot establish that the picked sheets are still the same ones. This
includes inserting or deleting sheets, undo and redo, and some macro or unrecorded changes.
A notice explains conservative clearing of a user-made selection. Pick the sheets again before acting.

The tree is rebuilt after changes, so the next Shift navigation starts a fresh range at the
keyboard cursor. Large lists can take longer to refresh. See [Known issues](./known-issues.md) for
the remaining synchronization work and the limits of detecting changes made by macros.
