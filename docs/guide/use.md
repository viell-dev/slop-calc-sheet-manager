# Use the sheet list

See the notice above for the version this guide describes. Changes marked **Unreleased** are not
in that published build. Before any build is published, the guide describes development. See
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

The grouped-editing warning appears only when several Calc tabs are grouped.
**Edits affect … Calc tabs** names the sheets affected by cell editing, even if the list's own
picks differ. Double-click a row,
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

Or use the context menu's **Move to top**, **Move up**, **Move down**, and **Move to bottom** actions.
Top and Bottom gather
the selected sheets, in their original order, at that end. Up and Down move each separate run of
selected sheets one place; a run already at the edge stays there. The moved sheets stay selected,
so pressing Up or Down again moves the same sheets further.

**Move buttons.** <Unreleased since="0.0.4" /> The **Top**, **Up**, **Down**, and **Bottom** buttons
above the list run the same actions.

A move is one **Move Sheets** undo step. The move preserves the active sheet and Calc's tab
selection. Use Ctrl+Z to undo it. **Undo and Redo of a move.** <Unreleased since="0.0.8" /> Undo and
Redo of the list's own move keep the list's picks, the viewed sheet and Calc's tab selection, so you
can undo a move and try again with the same rows picked. With undo history set to one step, and
after other changes described in [When the list clears its
selection](#when-the-list-clears-its-selection), Undo and Redo still clear the picks and Calc's view
can change; check the highlighted rows before the next move then. A stale selection or a move that
cannot be fully undone is refused with an explanation. Unavailable menu actions are disabled, with a
reason in their help text, such as a protected workbook structure, recorded changes, disabled undo,
no selection, or an edge. Native popup rendering can hide unavailable actions and their reasons; see
the [known issue](./known-issues.md).

## Open the sheet tab menu

Right-click a row to open its context menu without selecting it. If the row is already picked,
actions target the picked set; otherwise they target just that row. Menu or Shift+F10 targets the
list's picks.

**Context view.** <Unreleased since="0.0.4" /> Opening this menu leaves the viewed sheet and
Calc's selected tabs unchanged.

**Sheet commands.** <Unreleased since="0.0.5" /> The menu offers four of Calc's sheet commands
directly, under Calc's own names:

| Command | Acts on |
| --- | --- |
| Insert Sheet… | One sheet: Calc's dialog inserts before or after it |
| Delete Sheet… | Every target: Calc asks first when a sheet holds data |
| Rename Sheet… | One sheet |
| Hide Sheet | Every target, while another sheet stays visible |

A command is unavailable where it cannot act on exactly its targets: Insert and Rename when the
menu targets several sheets, every command for hidden sheets, and Delete for protected sheets.
<Unreleased since="0.0.6" /> For several sheets, **Rename Sheets…** takes Rename Sheet's place; see
[Rename several sheets](#rename-several-sheets).
They are also unavailable in a read-only document or one whose sheet structure is protected,
Rename for a protected sheet, Delete while changes are recorded, and Delete and Hide when no other
sheet would stay visible. Calc's own sheet tabs keep their full menu, including your
customizations, for every other command. Duplicate Sheet and Move or Copy Sheet are only there;
see [Known issues](./known-issues.md). Test builds up to 0.0.4 offer **Sheet actions…** instead,
which opens Calc's customized menu.

**Choosing a command.** <Unreleased since="0.0.5" /> Closing the menu without choosing anything
changes nothing. A chosen command first checks its sheets again: if one was renamed, replaced or
hidden since the menu opened, or became protected where the command does not allow that, nothing
runs and a message explains why. Calc's selected tabs are then set to exactly the targets, and Calc
stays on them afterwards, as it does after its own tab menu, even if you cancel the command's
dialog. If Calc reports an error once the command has started, Calc also stays on the targets
and a message asks you to check them. Insert Sheet and Rename Sheet apply to the viewed sheet
when you confirm them. When several sheets were targeted, they stay grouped and the footer shows
the group. Built-in commands keep Calc's confirmation and undo behaviour. Opening the menu leaves
the list's picks unchanged; a command's result can still clear them under the sheet-identity
rules, such as when a picked sheet is renamed or deleted.

**Mixed visibility.** <Unreleased since="0.0.4" /> When visible and hidden sheets are picked
together, Calc's commands are unavailable for them; Show Sheet and the move actions remain.
<Unreleased since="0.0.6" /> So does Rename Sheets…, which renames hidden sheets too.

**Hidden sheets.** <Unreleased since="0.0.5" /> When any target is hidden, **Show Sheet** takes
Hide's place and shows the hidden targets in one undo step where safe. Calc's commands are
unavailable for these targets, because Calc cannot view a hidden sheet.

The move actions follow the commands. Native popup rendering can hide unavailable entries and
their reasons; see the [known issue](./known-issues.md).

**Sheet Manager Help** opens this guide. The header's native `?` uses an unavailable LibreOffice
help topic; see [Known issues](./known-issues.md).

## Rename several sheets

**Rename Sheets.** <Unreleased since="0.0.6" /> When the menu targets two or more sheets, **Rename
Sheets…** takes the place of Rename Sheet… and opens one dialog for all of them. One sheet is still
renamed with Calc's own Rename Sheet…. Nothing changes until you choose **Rename**.

1. Pick the sheets in the list, then right-click one of them, or press Menu or Shift+F10, and
   choose **Rename Sheets…**. Hidden sheets can be included.
2. The dialog lists each sheet as its current name, an arrow, and its new name. Rows that are not
   changing say so.
3. To change part of every new name, type the text in **Find** and what replaces it in **Replace
   with**, then choose **Replace All**. The text is matched exactly, letter case included, and
   anything typed is plain text, not a pattern. Leave Replace with empty to remove the text, such
   as a shared prefix. Replace All can be repeated with other text.
4. To change one name, select its row and edit **New name**.
5. **Reset All** puts every current name back. **Rename** applies the new names; **Cancel** or
   Esc closes the dialog and changes nothing.

For example, pick `WIP North`, `WIP South`, and `WIP West`, type `WIP ` (with its space) in Find,
leave Replace with empty, and choose Replace All: the new names are `North`, `South`, and `West`.

A row that cannot be renamed shows ⚠ and the reason, and Rename stays unavailable until every row
is correct. The status line below the list explains the selected row, or counts the changes. A new
name is refused when it:

- is empty, contains `:` `\` `/` `?` `*` `[` or `]`, or begins or ends with an apostrophe;
- is another sheet's name, now or after the renames;
- is too close to another sheet's name: Calc treats names that differ only in letter case as the
  same name, and the dialog also refuses a few pairs that LibreOffice can confuse, such as `ß` and
  `ss`, or the dotted and dotless i (`I`, `İ`, `i`, `ı`).

Names are used exactly as typed. Spaces at either end are kept, and the list shows such names in
quotation marks. Sheets can swap names, or pass them around in a cycle; the dialog renames them
in a safe order.

All the renames are one **Rename Sheets** undo step. The viewed sheet and Calc's selected tabs do
not change, and the list keeps the renamed sheets picked under their new names. Formulas, named
ranges, and charts that refer to the sheets follow the new names. A sheet name written as text,
such as in `INDIRECT("'WIP North'.A1")`, is not changed; see
[Known issues](./known-issues.md).

Rename Sheets is unavailable, with the reason in its help text, in a read-only document, when the
sheet structure is protected, when a target sheet is protected, or when undo is off. If the sheets
change while the dialog is open, Rename refuses and says so in the dialog; cancel and try again.
If Calc refuses a name part-way, Rename Sheets undoes its own step, checks that every sheet has
its old name again, and says which name Calc refused. If it cannot confirm that, a message asks
you to check the sheet names.

The dialog opens with Find focused. Tab and Shift+Tab move through its fields, list, and buttons,
and Alt with a control's underlined letter goes straight to it. Enter in a field does not rename:
choose Rename. Esc cancels.

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

The four move shortcuts apply while the list has focus, without changing Calc's shortcut
configuration. In a cell, Alt+Down retains Calc's Data Select command.
Ctrl+Shift with navigation adds a range to the existing selection.

**Move-button shortcuts.** <Unreleased since="0.0.4" /> Move shortcuts also apply while a move
button has focus.

Space and Shift+Space do nothing in the list. <Unreleased since="0.0.4" /> Tab and Shift+Tab traverse
the enabled move buttons and the list, then return focus to Calc at either end. On a focused
button, Enter or Space runs that move; typing letters cannot enter cell content.
F6, F10, Esc, and unbound
Alt menu mnemonics retain LibreOffice's behaviour. Keys used by the list do not type into cells.
Other documents keep their
own keyboard handling. After Ctrl+S, focus moves to the sheet; use the focus cycle to return.

Rows use LibreOffice's native tree control and its accessible names: the sheet name, with hidden,
protected, and scenario states written in text. The current-sheet arrow and tab-colour square are
painted only. <Unreleased since="0.0.9" /> The list itself is named after the sheet Calc shows, for
example "Sheets, current sheet: Bravo", so assistive technology can tell the viewed sheet from the
selected rows; the name changes when another sheet is shown
([#83](https://github.com/viell-dev/slop-calc-sheet-manager/issues/83)). Tab colours are not
announced. <Unreleased since="0.0.9" /> The move buttons, the list and the footer messages are
reported to assistive technology in the order they appear, so it can reach them by moving through
the sidebar as well as by keyboard focus
([#133](https://github.com/viell-dev/slop-calc-sheet-manager/issues/133)). Automated checks read
this information through LibreOffice's accessibility interface; what a particular screen reader
announces is not verified (see [Known issues](./known-issues.md)).

## When the list clears its selection

LibreOffice's sheet handles can change which sheet they refer to after a deletion. The list clears
its selection when it cannot establish that the picked sheets are still the same ones. This
includes inserting or deleting sheets, undo and redo, and some macro or unrecorded changes.
A notice explains conservative clearing of a user-made selection. Pick the sheets again before acting.

**Undo and Redo of the list's moves.** <Unreleased since="0.0.8" /> Undo and Redo of a move the list
made itself, by dragging, a move button, the menu or a shortcut, keep the picks and the view. The
list recognizes its own move only when nothing that could change which sheet is which has happened
since: Undo and Redo of anything else, an inserted, deleted or replaced sheet, a new window of the
workbook, a macro adding actions to the move's undo step, or undo history set to one step still
clear the picks as before.

**Panel notice.** <Unreleased since="0.0.5" /> This explanation appears within the panel and
disappears after ten seconds, without changing keyboard focus or dismissing a grouped-editing
warning. In 0.0.4, the notice is an infobar that you close yourself.

Calc's Undo may also change the active sheet and native tab selection. After a grouped move, it can
activate the sheet immediately above the restored group; after a single move, it can activate the
restored sheet itself. When the list clears its picks, it follows that native selection. <Unreleased
since="0.0.8" /> After Undo or Redo of the list's own move, the list puts back the active sheet and
tab selection that each window of the workbook had just before
([#91](https://github.com/viell-dev/slop-calc-sheet-manager/issues/91)).

The list keeps its range anchor through ordinary refreshes while that sheet identity remains
valid. Large lists can take longer to refresh. See [Known issues](./known-issues.md) for
refresh costs and the limits of detecting changes made by macros.
