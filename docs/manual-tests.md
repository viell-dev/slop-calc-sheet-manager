# Optional desktop observations

Automated tests cover the sheet list with real mouse and keyboard input only on Linux, under a
virtual X display with the gtk3 and gen interfaces. On Windows they can send only LibreOffice's
own synthetic events, which bypass the key handler and cannot start a native drag. These checks
cover observations outside the automated evidence: real keys and drags on Windows, input in an
explicit Wayland session, and the list's appearance. These are optional checks, not an owner
checklist or a routine release gate. A release PR assesses any material evidence limit and makes
a narrowly scoped request only when the observation is unavailable to agents and blocks that
release. An X11 result does not establish Wayland input behaviour.

## Prepare

1. Download the build to be tested from [Releases and test builds](./guide/releases.md), or build
   the development package as [Install](./guide/install.md#install) describes. Install its `.oxt`
   with Tools ▸ Extension Manager ▸ Add, then restart LibreOffice.
2. Create the synthetic workbook: `python tools/manual_workbook.py` writes
   `dist/sheet-manager-manual-tests.fods`. Open it, then save it with File ▸ Save As as
   `manual-tests.ods` in a scratch folder, so that saving later needs no format question.
3. Open the Sheet Manager deck from its button in the sidebar's tab bar.

Report, for the whole run: the operating system, the LibreOffice version and the "VCL" line from
Help ▸ About, the number of each step that did not behave as described, and what happened
instead. Take screenshots only of this workbook.

## Checks

1. **List.** Look at the list.
   Expected: 60 rows in the order of the tab bar. Alfa, Bravo, and Charlie show red, green, and
   blue squares. Hotel and India read "(hidden)", Kilo reads "(protected)", and the active sheet
   has a separate arrow in its left gutter. Highlights and dividers span the row width.
2. **Click.** Click the row "Echo".
   Expected: Echo is selected across the row and Calc stays on its previous sheet. Repeat at
   the left edge and trailing whitespace. Double-click Echo: Calc shows it and the gutter arrow
   moves there.
3. **Selection without activation.** Ctrl+click "Golf", then Shift+click "Juliett".
   Expected: the list selects Golf to Juliett; Calc still shows Echo and only Echo's tab is
   selected in the tab bar.
4. **Wheel.** Turn the mouse wheel over the list, both ways.
   Expected: the list scrolls; nothing else changes. Drag the scrollbar too, including to the
   last row. Dividers stay one pixel thick and no line crosses the scrollbar. The last row's
   lower divider can be absent at the end of a long list; see [Known issues](./guide/known-issues.md).
5. **Drag two sheets above a row.** Click "Bravo", Ctrl+click "Delta", press on "Delta", and drag
   until the pointer is in the upper half of "Lima"; hold still for a moment, then release.
   Expected: during the drag a line marks the gap above Lima. After release the order starts
   Alfa, Charlie, Echo, Foxtrot, Golf, Hotel, India, Juliett, Kilo, Bravo, Delta, Lima, and Bravo
   and Delta stay selected in the list. Calc still shows the sheet it showed before.
6. **One undo step.** Click a cell, then press Ctrl+Z once.
   Expected: the original order returns.
7. **Drag below a row.** Repeat step 5, but release in the lower half of "Lima", then undo.
   Expected: Bravo and Delta land after Lima instead of before it.
8. **Auto-scroll and Esc.** Drag "Alfa" to the bottom edge of the list and hold it there; when
   the list has scrolled, press Esc, then release the mouse button.
   Expected: the list scrolls while held at the edge; after Esc nothing moves and Edit ▸ Undo has
   no new "Move Sheets" entry.
9. **Drop in place.** Drag "Echo" a little and release it on the lower half of "Echo".
   Expected: nothing changes and no undo entry is added.
10. **Drag out of the list.** Drag "Echo" out of the panel and release it over the sheet's cells.
    Expected: nothing is inserted into any cell and no sheet moves.
11. **Keys stay in the list.** Click cell A1, then click the row of the active sheet. Type `q`,
    wait a second, type `k`, press Down, then Space, Shift+Space, Ctrl+Space, Delete, Backspace,
    and `z`.
    Expected: typing `q` selects Quebec, `k` selects Kilo, Down selects Lima, and `z` selects
    Zulu. A1 still reads "Cell A1 of …; keep this text", no column or row is selected in the
    sheet, and the document is not marked as modified.
12. **Enter and navigation.** With the list focused, press Home, End, Page Up, Page Down, and
    Shift+Up, then type `m` and press Enter.
    Expected: the selection moves in the list only, Shift extends it, and Enter shows Mike.
13. **Shortcuts.** With the list focused, press Ctrl+Page Down, then Ctrl+Page Up.
    Expected: Calc shows the next sheet, then the previous one, and the list follows.
14. **Undo and save from the list.** Type text into a cell and press Enter, click a row of the
    list, press Ctrl+Z, type text into a cell again, click a row, and press Ctrl+S.
    Expected: Ctrl+Z removes the text; Ctrl+S saves without a dialog and the document's modified
    indicator in the status bar clears.
15. **Menu by right click.** Click "Charlie", Ctrl+click "Echo", and right-click "Echo".
    Expected: move actions appear directly; picks, viewed sheet and Calc tab group stay unchanged
    while this outer menu is open. Choose **Sheet actions…** to open Calc's customized menu,
    then choose Hide Sheet: exactly Charlie and Echo are hidden. Press Ctrl+Z. Right-click an
    unpicked row and cancel: picks, view and Calc tab group remain unchanged throughout.
    Sheet Manager Help opens the guide.
16. **Menu by keyboard.** Click "Golf" and press the Menu key; press Esc. Then press Shift+F10.
    Expected: the same menu opens each time, positioned at the Golf row.
17. **Activation ends grouped editing.** Group Charlie and Echo using Calc's tab bar. Double-click
    "Charlie" in the list, click a cell of the sheet, type `x`, and press Enter.
    Expected: the tab bar shows only Charlie selected, and the `x` appears only on
    Charlie, not on Echo. Delete the `x` afterwards.
18. **Keyboard position survives changes.** Open Window ▸ New Window. In the first window click
    "Bravo" and press Ctrl+Down twice. In the second window colour another sheet's tab with
    Sheet ▸ Sheet Tab Color, return to the first window, and press Ctrl+Space.
    Expected: Bravo and Delta are selected: the keyboard position stayed on Delta. Close the
    second window.
19. **Hidden sheets only.** Click "Hotel" (hidden), then right-click it.
    Expected: Calc's active sheet does not change; Show Sheet shows Hotel as one undo step.
    The menu also offers guarded movement and Help. Undo, then select Charlie and Hotel together.
    Open their menu and choose **Sheet actions…**: mixed targets use a safe menu offering Show
    Sheet, guarded moves and Help. Show Sheet shows only Hotel in one undo step.
20. **Other windows.** Open a second workbook, type in its cells, and use its shortcuts; then
    return to the first workbook and click a row of its list.
    Expected: the second workbook behaves exactly as without the extension; the first list still
    works.
21. **Another deck.** Switch the sidebar to the Properties deck and type into a cell.
    Expected: typing reaches the cell as usual.
22. **Look.** Repeat step 1 and step 5 with a dark theme and, if available, at 150 % or 200 %
    display scaling.
    Expected: all text and swatches are readable and the insertion line is visible.
    Before testing each top move button, select Charlie and Echo. Click the button, then undo once.
    Expected: each move preserves the picked order, selection and view. Calc's Undo can activate
    an affected sheet and the list follows, so select both rows again before the next button.
    Use Shift+Tab from the list to reach Bottom, Down, Up and Top. Enter/Space activate a focused
    button; ordinary letters do not edit cells. Tab at the end of the controls returns to Calc.
23. **Sheets added during a selection.** Click "Charlie" and Ctrl+click "Echo". Then choose
    Sheet ▸ Insert Sheet at End and confirm.
    Expected: the list no longer selects Charlie and Echo, and an information bar above the sheet
    says that the selection was cleared because sheets may have been added, removed, or renamed.
    Close the bar and delete the new sheet.
    <Unreleased since="0.1.0" /> The explanation appears inside the panel and disappears after ten seconds.
    Before it expires, click another row. Expected: expiration leaves that row picked and focus
    in the list; typing a letter searches the list rather than editing a cell. If Calc tabs are
    grouped, their separate warning remains. Repeat in another document while the first notice
    expires; the first document must not become active.
24. **Top.** Click Charlie and Ctrl+click Echo, then choose Move to top from the context menu.
    Expected: Charlie and Echo become the first two sheets, in that order, remain selected, and
    Calc keeps its active sheet. One Undo restores the original order.
25. **Up.** Select Charlie and Echo again and choose Move up twice, reopening the menu each time.
    Expected: each separate selected run moves one place per action, stopping at an edge. Each
    action is one undo step and keeps the same sheets selected. Undo twice.
26. **Down.** Select Charlie and Echo and choose Move down twice, then undo twice.
    Expected: each run moves one place per press, with the gaps preserved until runs meet an
    edge or each other; the same sheets stay selected and each action is one undo step.
27. **Bottom.** Select Charlie and Echo and choose Move to bottom, then undo.
    Expected: Charlie and Echo are the last two sheets, in that order, still selected.
28. **Move shortcuts and focus.** Repeat steps 24–27 with Alt+Home, Alt+Up,
    Alt+Down, and Alt+End while the list is focused. Use Menu or Shift+F10 to reach move actions
    by keyboard, then cancel and use Tab or Shift+Tab to leave the list.
    Expected: shortcuts match the context actions, a successful move returns focus to the list,
    and list keys do not type into cells. Both Tab directions return focus to Calc. Unavailable
    move actions cannot run. Native rendering may hide disabled actions and their help text;
    use Down to highlight the first available entry in the gen backend.
