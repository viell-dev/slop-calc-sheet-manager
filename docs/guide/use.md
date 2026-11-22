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

<Unreleased since="0.0.9" /> The list follows LibreOffice's document background colour. Text and
dividers stay readable, including when a custom scheme would otherwise give the text and
background the same colour. Selected rows keep the platform's selection and text colours
together; if the new background hides the selection, the list uses a distinct selection colour
with readable text. <Unreleased since="0.0.10" /> This adjustment keeps the native selection's
tint where possible. Sheet-tab colour squares keep their assigned colours. Appearance changes
follow when the visible list is idle; they leave your picks and the workbook unchanged.

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

**Disabled move and Rename buttons.** <Unreleased since="0.0.10" /> Their labels stay visible on
Linux with LibreOffice's theme enabled. They remain unavailable until their action is allowed.

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
sheet would stay visible. <Unreleased since="0.0.9" /> Delete is also unavailable for either of
two sheets whose names Calc confuses, because Undo can leave the sheet deleted; rename one of
them first, as [Known issues](./known-issues.md) explains. Calc's own sheet tabs keep their full
menu, including your customizations, for every other command. Duplicate Sheet and Move or Copy
Sheet are only there; see [Known issues](./known-issues.md).

**Choosing a command.** <Unreleased since="0.0.5" /> Closing the menu without choosing anything
changes nothing. A chosen command first checks its sheets again: if one was renamed, replaced or
hidden since the menu opened, or became protected where the command does not allow that, nothing
runs and a message explains why. Calc's selected tabs are then set to exactly the targets, and Calc
stays on them afterwards, except for Hide Sheet below, even if you cancel the command's dialog.
If Calc reports an error once the command has started, Calc also stays on the targets
and a message asks you to check them. Insert Sheet and Rename Sheet apply to the viewed sheet
when you confirm them. When several sheets were targeted, they stay grouped and the footer shows
the group. Built-in commands keep Calc's confirmation and undo behaviour. Opening the menu leaves
the list's picks unchanged; a command's result can still clear them under the sheet-identity
rules, such as when a picked sheet is renamed or deleted.

**Hiding other sheets.** <Unreleased since="0.0.10" /> Hide Sheet returns to the sheet you were
viewing if it
remains visible and can still be verified. Its previous Calc tab group is restored without the
sheets just hidden. If you hide the viewed sheet itself, Calc chooses another visible sheet.
If other changes prevent safe restoration, a message asks you to check the viewed sheet and
grouped tabs before editing.

**Mixed visibility.** <Unreleased since="0.0.4" /> When visible and hidden sheets are picked
together, Calc's commands are unavailable for them; Show Sheet and the move actions remain.
<Unreleased since="0.0.6" /> So does Rename Sheets…, which renames hidden sheets too.

**Hidden sheets.** <Unreleased since="0.0.5" /> When any target is hidden, **Show Sheet** takes
Hide's place and shows the hidden targets in one undo step where safe. Calc's commands are
unavailable for these targets, because Calc cannot view a hidden sheet.

The move actions follow the commands. Native popup rendering can hide unavailable entries and
their reasons; see the [known issue](./known-issues.md).

**Sheet Manager Help (online)** <Unreleased since="0.0.10" /> opens this guide in your browser.

The header's native `?` <Unreleased since="0.0.10" /> opens a short bundled English help page in
LibreOffice's internal viewer. It explains picks versus Calc tabs, movement and recovery, and links
to the full online guide. It works offline on builds with XML-help support. Use the online menu
action if that optional LibreOffice component is unavailable.

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

- is empty, contains `:` `\` `/` `?` `*` `[` `]` or a null character, or begins or ends with an
  apostrophe;
- is another sheet's name, now or after the renames;
- is too close to another sheet's name: Calc treats names that differ only in letter case as the
  same name, and the dialog also refuses a few pairs that LibreOffice can confuse, such as `ß` and
  `ss`, or the dotted and dotless i (`I`, `İ`, `i`, `ı`).

With a screen reader, move to **Sheets** with Alt+S and use the arrow keys to hear each refused
proposal and its reason. <Unreleased /> **New name** reports the selected proposal's refusal
while you edit. If that proposal is valid and another is refused, the field gives the first
affected sheet and its reason. Clearing **New name** leaves the empty-name reason on its preview
row. As you start typing again, the field can repeat a refusal on another row. An apostrophe at
the end of a proposal can trigger a warning as you type, for example at `Bob'` on the way to
`Bob's`. When the proposal becomes valid and no other row is refused, the field returns to its
ordinary name.

<Unreleased /> **Replace All** reports when Find is empty, when there are no matches, or when the
search matches but the replacement leaves every proposed name unchanged. It reports the first
affected sheet and reason if the replacement leaves a refused proposal. If you repeat the same
replacement and the first press already replaced every match, the conflict stays available on
the button. If the sheets changed since the dialog opened, **Rename** gives the refusal and asks
you to cancel and try again. Pressing **Rename** again while it has focus and the reason is the
same produces no new announcement. Move focus away and back with Tab or Shift+Tab to hear the
button's result again before editing a proposal or selecting another row.
See [known issues](./known-issues.md#known-issues) for tested screen-reader behavior.

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
Ctrl+Shift with navigation adds a range to the existing selection. <Unreleased /> After Ctrl with
an arrow, Home or End key moves the keyboard cursor, a range made with Shift or Ctrl+Shift, by
key or by click, starts at the cursor, where the list shows it. A Shift+click or
Ctrl+Shift+click made so quickly after such a key that the list has not shown the cursor there
yet picks nothing and clears the selection: click again
([#313](https://github.com/viell-dev/slop-calc-sheet-manager/issues/313)). <Unreleased /> When
another window renames the sheet under the keyboard cursor, keys keep moving from that row until
the list shows the new name, and they do not select the renamed sheet until then
([#314](https://github.com/viell-dev/slop-calc-sheet-manager/issues/314)).

**Move-button shortcuts.** <Unreleased since="0.0.4" /> Move shortcuts also apply while a move
button has focus.

Space and Shift+Space do nothing in the list. <Unreleased since="0.0.4" /> Tab and Shift+Tab traverse
the enabled move buttons and the list, then return focus to Calc at either end. On a focused
button, Enter or Space runs that move; typing letters cannot enter cell content.
F6, F10, Esc, and unbound
Alt menu mnemonics retain LibreOffice's behaviour. Keys used by the list do not type into cells.
Other documents keep their
own keyboard handling. <Unreleased since="0.0.8" /> After Ctrl+S, the list keeps or gets back the
focus. See [upgrade advice](./known-issues.md#upgrading-older-builds) for earlier builds.

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
<Unreleased /> A selection made through assistive technology that the list has not taken yet is
cleared the same way ([#265](https://github.com/viell-dev/slop-calc-sheet-manager/issues/265)), and
so is the selection when LibreOffice fails to show it in the list
([#257](https://github.com/viell-dev/slop-calc-sheet-manager/issues/257)).
<Unreleased /> A Ctrl+click or Ctrl+Space made as the list clears its selection, or drops a
picked sheet that another window renamed, picks nothing, and the next toggle acts. Before the list
shows its selection again after such a failure, a toggle also clears the selection, with the
notice
([#288](https://github.com/viell-dev/slop-calc-sheet-manager/issues/288)).
<Unreleased /> A selection made through assistive technology that the list has not taken yet is
also cleared, with the picks it replaced, when a sheet is renamed or moved first
([#280](https://github.com/viell-dev/slop-calc-sheet-manager/issues/280)). A Ctrl+click made
just after a selection key, before the list shows that key's change, picks nothing and clears
the selection, with the notice. So do a Ctrl+click, Ctrl+Space, and Ctrl with an arrow, Home or
End key on such a selection once the list has seen it, also when several Ctrl+clicks come at
once. Select again; the next toggle acts
([#291](https://github.com/viell-dev/slop-calc-sheet-manager/issues/291)).
<Unreleased /> They do so too just after rows were selected or cleared through assistive
technology, before the list has looked at that selection, and so do a Ctrl+Shift+click, Space
and a right click: the list counts the changes to its selection that it did not make itself. A
right click there opens the menu for the clicked sheet alone
([#294](https://github.com/viell-dev/slop-calc-sheet-manager/issues/294)).
<Unreleased /> A click in the list just as the list redraws its rows, as it does when another window
moves, inserts, deletes or renames a sheet, is refused if the redraw changed the clicked row,
rather than act on the sheet that the redraw put under the pointer. So is a Shift+click on any
row, and a click on any row when the redraw moved the top row or scrolled the list, as it does
when the list gets shorter while scrolled to its end. A refused right click opens no menu, and a
refused left click clears the selection, with the notice when you had made it. Click again
([#293](https://github.com/viell-dev/slop-calc-sheet-manager/issues/293)).
<Unreleased /> A click is refused in the same way when the list scrolls just after it, before the
list has handled it: by the mouse wheel or the scroll bar, or by a key that moves the selection
out of view. So is a click that comes just as the panel's height changes and scrolls the list, as
it can when the selection notice appears or goes. A drag does not start when you begin it just as
the list redraws or scrolls its rows. Click or drag again ([#299](https://github.com/viell-dev/slop-calc-sheet-manager/issues/299),
[#295](https://github.com/viell-dev/slop-calc-sheet-manager/issues/295)).

**Undo and Redo of the list's moves.** <Unreleased since="0.0.8" /> Undo and Redo of a move the list
made itself, by dragging, a move button, the menu or a shortcut, keep the picks and the view. The
list recognizes its own move only when nothing that could change which sheet is which has happened
since: Undo and Redo of anything else, an inserted, deleted or replaced sheet, a new window of the
workbook, a macro adding actions to the move's undo step, or undo history set to one step still
clear the picks as before.

**Panel notice.** <Unreleased since="0.0.5" /> This explanation appears within the panel and
disappears after ten seconds, without changing keyboard focus or dismissing a grouped-editing
warning.

Calc's Undo may also change the active sheet and native tab selection. After a grouped move, it can
activate the sheet immediately above the restored group; after a single move, it can activate the
restored sheet itself. When the list clears its picks, it follows that native selection. <Unreleased
since="0.0.8" /> After Undo or Redo of the list's own move, the list puts back the active sheet and
tab selection that each window of the workbook had just before
([#91](https://github.com/viell-dev/slop-calc-sheet-manager/issues/91)).

The list keeps its range anchor through ordinary refreshes while that sheet identity remains
valid. Large lists can take longer to refresh. See [Known issues](./known-issues.md) for
refresh costs and the limits of detecting changes made by macros.
