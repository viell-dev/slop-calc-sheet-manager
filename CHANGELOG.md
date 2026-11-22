# Changelog

Notable changes to Sheet Manager, newest first. Version numbers are plain dotted numbers; see
[RELEASING.md](RELEASING.md#versions-and-titles) for why there are no prerelease suffixes.

## Unreleased

- A selection made through assistive technology just after a click or key in the sheet list,
  before the list has shown that input, is no longer replaced by what the input selected. Move to
  Top then moved the click's or key's sheets, though the selection showed last was another. The
  list now keeps that selection, and commands act on it. Where it cannot tell what you selected,
  after a Ctrl+click it refused, a Ctrl+double-click, a click held and released over another row,
  or a right click, it clears the selection with the selection notice instead; the right click's
  menu opens for the clicked sheet alone. A click on a row just after a key still selects the row
  clicked, and the list no longer scrolls to the key's selection over it
  ([#307](https://github.com/viell-dev/slop-calc-sheet-manager/issues/307)).
- A sheet list write that LibreOffice fails after you hold a click on the picked sheet and release
  it over another row no longer leaves that row to be taken as a pick. Move to Top could then move
  it, though nobody picked it. The list now clears the picks with the selection notice, as after
  a refused held click. LibreOffice's tree has been seen to fail such a call only while a panel
  closes ([#316](https://github.com/viell-dev/slop-calc-sheet-manager/issues/316)).
- After Ctrl with an arrow, Home or End key moved the keyboard cursor, a Ctrl+Shift+click now
  adds the range from the cursor that the list shows at the click. The list added the range from
  where the selection had started instead: the click was refused and cleared the selection, or,
  when both ranges had as many rows, the list replaced the range it had shown with the other, and
  Move to Top then moved sheets you had not selected. A Shift or Ctrl+Shift range made by key or
  click after such keys also starts at the cursor now. A Shift+click or Ctrl+Shift+click made so
  quickly after such a key that the list has not shown the cursor there yet picks nothing and
  clears the selection, since LibreOffice's list still ranges from the earlier cursor then
  ([#313](https://github.com/viell-dev/slop-calc-sheet-manager/issues/313)).
- A key pressed just after another window renamed the sheet under the keyboard cursor, before the
  list showed the new name, no longer moves from the first row of the list: Down selected the
  second sheet, and Move to Top then moved it. Keys now move from the row where the list showed
  the cursor, and do not select the renamed sheet until the list shows its new name
  ([#314](https://github.com/viell-dev/slop-calc-sheet-manager/issues/314)).
- The unit tests' simulated sheet list now runs the list's mouse handlers, keys, type-ahead and
  Move to Top through the extension's own mouse listener, key handler and move button listener,
  with their error guards, loaded from the extension's source. A LibreOffice failure inside a
  press's or a release's handler, a key or a Move to Top is then reported and ends only that
  input, and the list still queues its selection write after a mouse handler, as in LibreOffice.
  The failure escaped to the test instead, so tests caught it themselves and randomized checks
  built on the simulation stopped at such a sequence without judging it. A key the key handler
  never gives the list, such as a plain Space, can no longer reach it in these tests. This
  changes the unit tests, not the extension
  ([#312](https://github.com/viell-dev/slop-calc-sheet-manager/issues/312),
  [#320](https://github.com/viell-dev/slop-calc-sheet-manager/issues/320)).
- A Ctrl+click, Ctrl+Shift+click, Space, Ctrl+Space, right click, or Ctrl with an arrow, Home or
  End key, made just after rows were selected or cleared through assistive technology, no longer
  acts against the list's earlier picks before the list has taken that selection, within about a
  quarter of a second. Move to Top could then move a sheet you had just deselected or replaced.
  The list now counts the changes to its selection that it did not make itself, and such input
  picks nothing and clears the selection, with the selection notice: select again. Two clicks or
  keys made so quickly that the list has not handled the first when the second arrives can be
  refused in the same way
  ([#294](https://github.com/viell-dev/slop-calc-sheet-manager/issues/294)).
- When the list refuses a held click because the sheets changed during it, the keyboard cursor
  now stays where your keys moved it during the hold, also outside the picks, as long as the list
  can still identify that sheet. It returned to a picked sheet, so Ctrl+Space then toggled that
  sheet instead; the picks were already kept. Releasing another mouse button while the left one
  is held no longer ends the held click
  ([#71](https://github.com/viell-dev/slop-calc-sheet-manager/issues/71)).
- A sheet list write that LibreOffice fails right after the list refused a held click no longer
  leaves the row the button went up over to be taken as a pick. Move to Top could then move that
  sheet, or one that replaced the pressed sheet under its name, which nobody picked. The list now
  clears the picks with the selection notice and commands act on no sheets until you pick again.
  LibreOffice's tree has been seen to fail such a call only while a panel closes
  ([#315](https://github.com/viell-dev/slop-calc-sheet-manager/issues/315)).
- A click, double click or right click in the sheet list no longer acts on another sheet than the
  one you clicked when the list scrolls before it handles the click: by the mouse wheel or the
  scroll bar, or by a key such as End or Down that moved the selection out of view just before.
  The list took the sheet scrolled under the pointer: a double click could go to it, and the
  right-click menu could delete it. Such a click is now refused, as a click during a redraw is,
  and so is a click that comes just as the panel's height changes and scrolls the list. Click
  again ([#299](https://github.com/viell-dev/slop-calc-sheet-manager/issues/299)).
- A drag started in the sheet list just as the list redraws its rows, as it does when another
  window moves a sheet, no longer drags the sheets that were selected before instead of the
  sheet you pressed. Such a drag, and one started just as the list scrolls, now does not start:
  drag again ([#295](https://github.com/viell-dev/slop-calc-sheet-manager/issues/295)).
- The real-input lab's Rename Sheets dialog now calibrates with the sheet list's method, which
  takes the offset only from two reports of one point's own moves. When every report came later
  than the 0.3-second quiet time, the dialog could credit the previous point's pair of reports to
  the point being tried, and click 551 pixels beside its controls. Its points' rows are now
  15 pixels apart instead of 3, because the moves of points that close can pair falsely; the
  method now refuses points closer than 15 pixels. This changes the test runner, not the
  extension ([#300](https://github.com/viell-dev/slop-calc-sheet-manager/issues/300)).
- The real-input lab now tries points down the sheet list's accessible area before scanning the
  window, after waiting until the list is laid out, and a new workbook's calibration takes about
  a second. In gtk3, the area of a newly opened workbook was 21 pixels above the list, and when
  the first point was the pointer entering the list, it was not reported; either way the window's
  scan took 12 to 18 seconds per workbook. That scan also moved the pointer along the window's top
  row. In gtk3, in a window the lab had just placed, accessible places lay 25 pixels above where
  they lay after such moves, and without them a real click at the native sheet tab's accessible
  place hit the scroll bar; the cause is not established
  ([#309](https://github.com/viell-dev/slop-calc-sheet-manager/issues/309)). The lab now moves the
  pointer along that row after a calibration while the list's accessible place lies more than 10
  pixels from the calibrated one. Each session's results record its calibrations, with the
  check that made them. This changes the test runner, not the extension
  ([#301](https://github.com/viell-dev/slop-calc-sheet-manager/issues/301)).
- A selection made in the list through assistive technology is no longer replaced by the list's
  earlier picks when another window renames or moves a sheet before the list has taken it; Move
  to Top then moved the earlier picks. The list now clears both, with the selection notice, and
  you select again ([#280](https://github.com/viell-dev/slop-calc-sheet-manager/issues/280)).
- A Ctrl+click that deselects a sheet no longer picks it when it comes just after a selection key
  whose change the list has not drawn yet, or on a selection made through assistive technology
  that the list has seen but not taken yet, also when several clicks come at once; Ctrl+Space
  on such a selection no longer picks the row you meant to deselect, and Ctrl with an arrow,
  Home or End key no longer brings back the earlier picks over it. Such a
  toggle or key now picks nothing and clears the selection, with the selection notice, and until
  the list has redrawn, Ctrl+Space picks nothing either, also after arrow keys typed meanwhile:
  select again ([#291](https://github.com/viell-dev/slop-calc-sheet-manager/issues/291)).
- A click, Ctrl+click, Shift+click, double click or right click in the sheet list no longer acts
  on another sheet than the one you clicked when the list redraws its rows at that moment, as it
  does when another window moves, inserts, deletes or renames a sheet. The list handled the
  click only after the redraw and took the sheet then in that row: Move to Top could move a sheet
  you never clicked, a double click could go to it, and the right-click menu could delete it.
  This also happened on a row the redraw kept when the redraw scrolled the list, as it does when
  the list gets shorter while scrolled to its end. At such a moment, a click on a row that the
  redraw changed, on any row when it scrolled the list, and a Shift+click on any row, are now
  refused: a refused right click opens no menu, and a refused left click clears the list's
  selection, with the selection notice when you had made it. Click again
  ([#293](https://github.com/viell-dev/slop-calc-sheet-manager/issues/293)).
- The real-input lab's calibration of the sheet list now lets the list's reports of a point stop
  before it moves the pointer a second time, moves it toward the list's middle, and tries another
  point when that move goes unreported. Before, it waited 10 seconds and failed the session. gtk3
  drops a move made before it has finished with the previous report: beside other busy processes,
  one gtk3 calibration in five failed. The offset now comes only from two reports that belong to
  one point's two moves. A late report of an earlier point can no longer shift it, and reports
  that never follow the moves fail with the points tried. The Windows desktop checks use the same
  calibration. This changes the test runner, not the extension
  ([#298](https://github.com/viell-dev/slop-calc-sheet-manager/issues/298)).
- A Ctrl+click or Ctrl+Space that deselects a sheet in the list no longer picks that sheet
  instead when the list drops picks at the same moment, as it does when another window inserts
  or deletes a sheet or renames a picked one; Move to Top then moved the sheet you had just
  deselected. Until the list shows its picks again, such a toggle picks nothing and the list
  redraws its selection: toggle again. The same applies after LibreOffice fails a write to the
  list's tree, where the toggle also clears any other picks, with the selection notice, so that a
  command cannot act on sheets the list may not have shown
  ([#288](https://github.com/viell-dev/slop-calc-sheet-manager/issues/288)).
- A click's or a selection key's queued list update, and a sheet tab menu command chosen just
  before the document or the sidebar closes, now do nothing once the list is closed. Before, they
  reported a failure on stderr, and after only the sidebar closed the chosen command or Help still
  ran, although the list could no longer show why it refused or what failed
  ([#285](https://github.com/viell-dev/slop-calc-sheet-manager/issues/285)).
- A shortcut typed in the list just before the sidebar closes still reaches the document, now
  Save and Save As too. One typed just before the document closes is dropped, as LibreOffice
  drops its own, and one typed just before it reloads is dropped too, instead of reporting a
  failure or running on the reloaded document
  ([#285](https://github.com/viell-dev/slop-calc-sheet-manager/issues/285)).
- A click's release in the list and the start of a drag no longer check the document's sheet
  structure themselves. They run while LibreOffice lets other programs change the document, and
  such a check could then keep an outdated sheet count, so that a later deletion went unnoticed.
  They now rely on the changes the document has reported, and the activation, selection update
  or move that follows checks the structure before it acts
  ([#284](https://github.com/viell-dev/slop-calc-sheet-manager/issues/284)).
- Enter, type-ahead and the keyboard menu key no longer report a failure on stderr when the
  document or the sidebar closes between the key and its queued work, which now does nothing
  once the list is closed ([#282](https://github.com/viell-dev/slop-calc-sheet-manager/issues/282)).
- A double click in the list now activates its sheet after the mouse listener returns, as Enter
  already did: LibreOffice runs that listener without the global lock that reading Calc's
  selected tabs needs ([#269](https://github.com/viell-dev/slop-calc-sheet-manager/issues/269)).
- A sheet list write that LibreOffice fails partway no longer leaves part of it to be taken as
  the picks. Afterwards the list keeps its picks only if it shows exactly them. Otherwise it
  cannot tell part of its write from a selection made since, such as through assistive
  technology, so it clears the picks with the selection notice and commands act on no sheets
  until you pick again; a selection made that way in between is cleared too. A selection made
  through assistive technology just before the list lost track of which sheet is which, as when a
  sheet is replaced under its own name, or before a refresh that then failed, is cleared the same
  way rather than taken for another sheet or replaced by older picks. LibreOffice's tree has been
  seen to fail such a call only while a panel closes
  ([#257](https://github.com/viell-dev/slop-calc-sheet-manager/issues/257),
  [#265](https://github.com/viell-dev/slop-calc-sheet-manager/issues/265)).
- On Linux, a test session's forced stop now also stops a LibreOffice `soffice.bin` that outlives
  its launcher: one whose `oosplash` launcher was killed, or that `oosplash` had started but not
  yet taken over when it was told to stop, as at its first-start restart. Both were measured with
  LibreOffice 26.8.2.2; such an office kept running after the stop. The launcher is paused, with
  each of its threads stopped, while its processes are listed, and the stall receipt and a forced
  shutdown's results record what the stop saw of each. This changes the test runner, not the
  extension ([#266](https://github.com/viell-dev/slop-calc-sheet-manager/issues/266)).
- The painted soak now fails a session whose end it first sees after the session's 180-second
  limit, as when the soak's own process was not scheduled across that limit, instead of recording
  the runner's own status, which let a session that ended late pass. This changes the test
  runner, not the extension
  ([#275](https://github.com/viell-dev/slop-calc-sheet-manager/issues/275)).
- Give each CI job that runs LibreOffice time to keep the stacks of a stall at any point in a
  run of its measured length: routine CI's Linux job and the release sweep's Linux gtk3 jobs now
  have 60 minutes instead of 45, the sweep's headless Linux jobs 35 instead of 30, and its
  Windows integration job 40 instead of 25. The macOS integration runner now ends at a
  30-minute deadline, recording a stall with the test client's stacks, within the command's
  33-minute limit. This changes CI and the test helpers, not the extension
  ([#244](https://github.com/viell-dev/slop-calc-sheet-manager/issues/244)).
- The stall watch now waits for LibreOffice's gdb wrapper after an interrupt because its stack
  collector reports that it sent one, rather than by reading the start of its own receipt text,
  so rewording that text can no longer drop the wait and the wrapper's recorded exit status. This
  changes the test runner, not the extension
  ([#267](https://github.com/viell-dev/slop-calc-sheet-manager/issues/267)).
- On Windows, a test document close that was posted to LibreOffice's main thread before the
  stall watch recorded a stall no longer starts when that thread reaches it, so it cannot change
  the office while its stacks are being taken; the close helper then fails as after any stall.
  This changes the test runner, not the extension
  ([#261](https://github.com/viell-dev/slop-calc-sheet-manager/issues/261)).
- The painted soak now removes every session directory an earlier soak left in its output before
  its first session, so that a shorter soak's artifact no longer carries an earlier, longer
  soak's sessions. It follows no symbolic link there. This changes the test runner, not the
  extension ([#268](https://github.com/viell-dev/slop-calc-sheet-manager/issues/268)).
- A drag begun on sheet list rows that are out of date is still refused, but the list now
  refreshes after LibreOffice's drag-gesture callback returns rather than inside it, so that the
  refresh's reading of Calc's selected tabs no longer runs in that callback
  ([#264](https://github.com/viell-dev/slop-calc-sheet-manager/issues/264)).
- Make the integration check for assistive selection verify that the list takes the pick, using
  Move to Top with stable rows and after a rebuilding refresh
  ([#251](https://github.com/viell-dev/slop-calc-sheet-manager/issues/251)).
- Known issues now says the sheet list keeps rebuilding its rows after a sheet switch or tab
  colour change, and why
  ([#22](https://github.com/viell-dev/slop-calc-sheet-manager/issues/22)).
- When Replace All finds matching text but changes no proposed names, Rename Sheets explains
  this in the status and through the button's accessible name
  ([#259](https://github.com/viell-dev/slop-calc-sheet-manager/issues/259)).
- Fail a test session that stops making progress for 15 minutes instead of waiting for the CI
  job's time limit without evidence: the runner records the stall, tries to save the test
  client's and LibreOffice's stacks, stops the LibreOffice launcher it started (on Windows, with
  its whole process tree), and records what it tried and saw. Such a session then ends without the
  wait for queued UNO releases or a terminate request, as after a stalled main-thread callback. A
  soak session that reaches its 180-second limit during startup or its checks records the stall
  too. The soak empties each session's directory before the session starts, and its summary
  points there instead of judging stalls
  ([#45](https://github.com/viell-dev/slop-calc-sheet-manager/issues/45)).
- End each LibreOffice test session only after the office has run the UNO releases the test
  process sent before the session's end. An office asked to terminate while it still ran them,
  as after the 1,000-sheet check, could crash at exit in a LibreOffice bridge thread, with or
  without the extension. Releases sent during that wait are not covered, such as from a document
  that a failed check left open. The wait, the terminate request and the office's exit now share
  one 30-second limit. This changes the test runner, not the extension
  ([#242](https://github.com/viell-dev/slop-calc-sheet-manager/issues/242)).
- Make name syntax and conflicts in other rows available from New name in Rename Sheets.
  Replace All and Rename also expose refusals through their accessible names, including an empty
  Find field or a replacement with no matches
  ([#254](https://github.com/viell-dev/slop-calc-sheet-manager/issues/254)).
- Calibrate the rename dialog's real-input clicks on points of the dialog's own window, located
  from its buttons, rather than of its accessible area, which includes the window manager's
  frame. On the Windows desktop the frame's borders kept the dialog from reporting nearly every
  point, and each calibration took about a minute; it now takes under a second there and on
  Linux ([#253](https://github.com/viell-dev/slop-calc-sheet-manager/issues/253)).
- Expose the selected proposal's name conflict on the focused New name field in Rename Sheets,
  so a screen reader can announce the refusal while the user stays in the edit
  ([#247](https://github.com/viell-dev/slop-calc-sheet-manager/issues/247)).
- Record how long each integration-test installation of the package takes, as `install_seconds`
  in the results, and keep the elapsed time and unopkg's output when an installation exceeds its
  90-second limit, which still fails the session. The local testing guide says how to tell such a
  timeout on a busy computer from a normal installation
  ([#235](https://github.com/viell-dev/slop-calc-sheet-manager/issues/235)).
- Calibrate the rename dialog's real-input clicks from two reports that follow the pointer's two
  moves, rather than the first report after a fixed 0.15 seconds, which a busy office could send
  late enough to be read for the next point tried
  ([#232](https://github.com/viell-dev/slop-calc-sheet-manager/issues/232)).
- Organise contributor testing guidance by task and platform, with dedicated Development pages
  for native LibreOffice testing and hosted workflows
  ([#198](https://github.com/viell-dev/slop-calc-sheet-manager/issues/198)).
- Make more moves of a sheet whose name LibreOffice confuses with another sheet's, such as `fi`
  beside `ﬁ`. When the usual way of making a move needs the confused name, the list tries one
  other, equally short way, for example moving the sheet beside it, and refuses the move only if
  that way needs a confused name too
  ([#125](https://github.com/viell-dev/slop-calc-sheet-manager/issues/125)).
- Retain painted Linux integration evidence before release-sweep input tests and require the
  painted phase to succeed before input starts
  ([#192](https://github.com/viell-dev/slop-calc-sheet-manager/issues/192)).
- Check the documentation's availability markers at every marked version, including when
  a newer test build appears beside an older stable release
  ([#196](https://github.com/viell-dev/slop-calc-sheet-manager/issues/196)).
- Plan moves that reorder many sheets faster: planning the reversal of 10,000 sheets takes under
  a second instead of three to seven on a loaded laptop, with the same moves. The planning
  budget test now measures CPU time and reports it with the elapsed time
  ([#214](https://github.com/viell-dev/slop-calc-sheet-manager/issues/214)).
- Add contributor references for LibreOffice packaging, sidebar design and interface checks
  ([#201](https://github.com/viell-dev/slop-calc-sheet-manager/issues/201)).
- Keep verified package SHA-256 digests in deployed release history, so a replaced OXT and
  matching replacement checksum stop feed generation, and publish a release only when GitHub's
  digests of its uploaded files equal the files the workflow built
  ([#193](https://github.com/viell-dev/slop-calc-sheet-manager/issues/193)).
- Keep the move buttons usable when LibreOffice treats the focused document window as
  inactive. They could stay disabled while sheets were picked, until a dialog opened from the
  list; clicking or typing in the list now makes its window active, as switching to it does
  ([#211](https://github.com/viell-dev/slop-calc-sheet-manager/issues/211)).
- Show a message with reopening and reporting guidance when the sheet list cannot open, instead
  of an empty deck ([#188](https://github.com/viell-dev/slop-calc-sheet-manager/issues/188)).
- Retry a failed list refresh, so that a changed tab colour, visibility or protection is still
  shown afterwards ([#186](https://github.com/viell-dev/slop-calc-sheet-manager/issues/186)).
- Finish closing the panel when part of its cleanup fails, and keep a failure in a move button's
  callback from reaching LibreOffice
  ([#187](https://github.com/viell-dev/slop-calc-sheet-manager/issues/187),
  [#189](https://github.com/viell-dev/slop-calc-sheet-manager/issues/189)).
- Refresh the Debian 13 integration image digest and the checks image's Python to 3.12.16.
- Update the development checks image and local Node.js pin together to 24.22.2, including
  the documentation container example.
- Report unsupported rootless or UID-remapped Docker contexts before building the Linux lab
  ([#191](https://github.com/viell-dev/slop-calc-sheet-manager/issues/191)).
- Update development tools to pytest 9.2.0, Ruff 0.17.4, types-PyYAML 6.0.12.20261103 and
  nodeenv 1.12.0. These dependencies do not ship in the extension.
- Correct contributor guidance in the list, menu and Show module docstrings: a single click
  picks without switching sheets, Hide alone dispatches synchronously, and Show is one of
  several changes the list makes itself
  ([#200](https://github.com/viell-dev/slop-calc-sheet-manager/issues/200)).
- Move the sheet list's tab observation and refresh timing into modules of their own, with
  documented state contracts; the list behaves as before
  ([#194](https://github.com/viell-dev/slop-calc-sheet-manager/issues/194)).
- Bound LibreOffice lab downloads and log their mirror and transfer measurements, so a slow
  mirror fails during setup instead of consuming the native CI testing budget.
- Cache the pinned LibreOffice test installers by SHA-256 and verify them before use, avoiding
  repeat downloads from the TDF archive ([#215](https://github.com/viell-dev/slop-calc-sheet-manager/issues/215)).
- Keep a failed real-input check's record when its screenshot, desktop evidence or input
  clean-up also fails: the record is written first, and each later step's error is kept beside
  it ([#190](https://github.com/viell-dev/slop-calc-sheet-manager/issues/190)).
- Split the real-input test runner into a shared workbook fixture, the Xvfb lab, the check loop
  and check modules by subject, so that the Windows and update-dialog runners no longer import
  the Linux runner; the checks, their order and their evidence are unchanged
  ([#195](https://github.com/viell-dev/slop-calc-sheet-manager/issues/195)).
- Wait for the sheet list's own report of the lab's pointer calibration move instead of a fixed
  0.2 seconds. A late report had shifted a workbook's calibrated origin by two pixels and failed
  the painted-row check ([#209](https://github.com/viell-dev/slop-calc-sheet-manager/issues/209)).

- Put installation and a worked example first in the README, and align the guide's Hide
  summary and security policy with published behaviour
  ([#197](https://github.com/viell-dev/slop-calc-sheet-manager/issues/197),
  [#199](https://github.com/viell-dev/slop-calc-sheet-manager/issues/199)).
- Make two intermittent test failures classify themselves. A failed pick after Reload keeps
  the click's delivery, the list's selection events and later document modifications. The
  real-input grid click is no longer repeated, and a failed one records whether it arrived late
  ([#88](https://github.com/viell-dev/slop-calc-sheet-manager/issues/88),
  [#42](https://github.com/viell-dev/slop-calc-sheet-manager/issues/42)).
- Audit former macOS test process groups for a bounded time after each command exits, give
  timed-out groups a bounded TERM drain before KILL, and detach the disk image when a failed
  attach left it mounted ([#163](https://github.com/viell-dev/slop-calc-sheet-manager/issues/163)).

## 0.0.10 - 2026-11-03

Fourth beta towards the stable release 0.1.0, following the 0.0.9 usability review. It improves
disabled controls, selection colours and Hide behaviour, and adds bundled quick help. Requires
LibreOffice 26.2.1 or later with Python support. The next
[focused usability review](https://github.com/viell-dev/slop-calc-sheet-manager/issues/177)
precedes an RC; this build remains a beta.

- Open bundled English quick help from the sidebar header's `?`, including the distinction
  between list picks and Calc tabs, movement, Undo and recovery, and an online-guide link
  ([#81](https://github.com/viell-dev/slop-calc-sheet-manager/issues/81)).
- Keep disabled move and Rename labels readable on Linux with LibreOffice's theme enabled
  ([#166](https://github.com/viell-dev/slop-calc-sheet-manager/issues/166)).
- Keep the native selection tint when adapting it to the document background, instead of
  replacing a light blue selection with grey in dark appearance
  ([#167](https://github.com/viell-dev/slop-calc-sheet-manager/issues/167)).
- Keep the previous visible sheet when hiding other sheets from the list, restoring its Calc
  tab group without the hidden sheets where safe
  ([#168](https://github.com/viell-dev/slop-calc-sheet-manager/issues/168)).
- Use plain text consistently for the move controls and menu actions, and label the context
  menu's Help link as online help ([#169](https://github.com/viell-dev/slop-calc-sheet-manager/issues/169),
  [#81](https://github.com/viell-dev/slop-calc-sheet-manager/issues/81)).
- Refresh the pinned Python 3.12 development image.
- Update the development checks image and local Node.js pin together to 24.22.0, keeping the
  documentation container example aligned.
- Update setup-python to 7.1.0, Ruff to 0.17.2, and VitePress to 2.0.0-alpha.21 for development,
  CI and documentation builds.

## 0.0.9 - 2026-11-02

Third beta towards the stable release 0.1.0, following 0.0.8. It improves the sheet list's
appearance and accessibility, and refuses a Delete that Calc cannot safely undo. Requires
LibreOffice 26.2.1 or later with Python support.

- Follow Calc's document background throughout the sheet list, including its unused space
  ([#141](https://github.com/viell-dev/slop-calc-sheet-manager/issues/141)). Text and dividers stay
  readable as the colour scheme changes. Native selection colours are retained unless the
  document background hides the selection. Changing colours keeps the row height, picks, view
  and workbook state.
- Refuse Delete Sheet for either of two names that Calc confuses
  ([#138](https://github.com/viell-dev/slop-calc-sheet-manager/issues/138)). For example, Calc can
  accept both `ﬁ` and `fi` as sheet names but lose a deleted sheet when Undo tries to restore it.
  The extension's menu disables Delete with a reason naming both sheets. Rename one of them
  first. Calc's own tab menu and underlying name/formula handling remain outside this safeguard.
- Name the list after the sheet Calc shows, for assistive technology
  ([#83](https://github.com/viell-dev/slop-calc-sheet-manager/issues/83)). For example,
  "Sheets, current sheet: Bravo" changes when another sheet is shown. Rows retain their sheet
  names and hidden, protected or scenario state. An accessibility selection also survives a
  refresh that rebuilds the rows.
- Expose the list, move buttons and footer through the sidebar's accessible hierarchy
  ([#133](https://github.com/viell-dev/slop-calc-sheet-manager/issues/133)). The gtk3 bridge now
  reports their focus, rows and viewed-sheet name changes. What a particular screen reader
  announces remains unverified. Clicking or dragging in empty panel margins keeps the sidebar
  docked.

Verification now includes packaged headless integration and removal on Intel macOS 15 with the
official LibreOffice 26.8.2.2 build. Aqua rendering, real OS input, Apple Silicon, screen readers,
GUI installation/update and upgrades from published builds on macOS remain unverified. Linux and
Windows input checks continue, with broader platform checks required in a manual release sweep.
Regression checks also exercise identifying-cell view restoration and guarded Delete/Undo with
both measured confusable-name pairs
([#128](https://github.com/viell-dev/slop-calc-sheet-manager/issues/128),
[#145](https://github.com/viell-dev/slop-calc-sheet-manager/issues/145)).
The 1,000-sheet checks also measure context-menu construction and verify Delete safety
([#22](https://github.com/viell-dev/slop-calc-sheet-manager/issues/22)); routine Linux CI retains
headless diagnostics before input starts and preserves failed runner status
([#152](https://github.com/viell-dev/slop-calc-sheet-manager/issues/152)). Its timeout and required
success gate are unchanged.
Static checks cover Linux, Windows and macOS API availability; native test failures retain
more diagnostics, and the identity fixture waits for the list to finish refreshing after Undo
([#159](https://github.com/viell-dev/slop-calc-sheet-manager/issues/159),
[#160](https://github.com/viell-dev/slop-calc-sheet-manager/issues/160),
[#162](https://github.com/viell-dev/slop-calc-sheet-manager/issues/162)).
Native theme checks prepare their workbook before opening the panel, keeping all UI checks visible.

Install the OXT manually over 0.0.8 or an earlier build, restart LibreOffice when asked, and check
its SHA-256 asset. LibreOffice's Extension Manager offers only stable releases, and there is none
yet, so later test builds remain manual downloads. See the
[known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues) for the
remaining limits. A focused human usability review is still required before a release candidate;
[#130](https://github.com/viell-dev/slop-calc-sheet-manager/issues/130) tracks preparation of a new
request. The plan towards 0.1.0 is in
[#93](https://github.com/viell-dev/slop-calc-sheet-manager/issues/93).

## 0.0.8 - 2026-10-31

Second beta towards the stable release 0.1.0, following 0.0.7. It fixes two defects in the
main workflow; the feature set is unchanged. Requires LibreOffice 26.2.1 or later with Python
support.

- Keep the list's picks and the view through Undo and Redo of its own moves
  ([#91](https://github.com/viell-dev/slop-calc-sheet-manager/issues/91)). After dragging sheets
  or moving them with a button, the menu or a shortcut, Ctrl+Z and Ctrl+Y no longer clear the
  picked rows, and the sheet you were viewing and Calc's selected tabs stay as they were instead
  of jumping to a moved sheet. The list recognizes its own move only when nothing that could
  change which sheet is which has happened since; otherwise Undo and Redo still clear the picks
  and show the notice, as before. With undo history set to one step they always do. If a move
  fails before it moves any sheet, Redo history from before the move is now lost.
- Keep the keyboard focus in the sheet list after Ctrl+S
  ([#23](https://github.com/viell-dev/slop-calc-sheet-manager/issues/23)). With LibreOffice's
  gtk3 interface on Linux, a save moves the focus from any sidebar control to the sheet, Calc's
  own panels included. The list now takes it back once the save has finished, after any Save As,
  file format, or error dialog has closed, so typing goes on searching the list instead of
  editing a cell. A dialog keeps the focus while it is open.

Install the OXT manually over 0.0.7 or an earlier build, restart LibreOffice when asked, and check
its SHA-256 asset. LibreOffice's Extension Manager offers only stable releases, and there is none
yet, so later test builds remain manual downloads. Known limits are in the [known
issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues). This is the build
for the usability pass that the stable release requires: the tasks are in
[#130](https://github.com/viell-dev/slop-calc-sheet-manager/issues/130), and anyone familiar with
Calc can do them. The plan towards 0.1.0 is in
[#93](https://github.com/viell-dev/slop-calc-sheet-manager/issues/93).

## 0.0.7 - 2026-10-31

First beta towards the stable release 0.1.0, following the 0.0.6 alpha. The features planned
for 0.1.0 are complete; the remaining work before a release candidate is fixing the logged
defects and polishing. Requires LibreOffice 26.2.1 or later with Python support.

- Sheets whose names Calc's own lookup cannot tell apart, such as `ﬁ` beside `fi`, or `ı` beside
  `I`, now show their own hidden, protected and colour states, and the list acts on them instead
  of refusing every action with "The sheet list has changed"
  ([#113](https://github.com/viell-dev/slop-calc-sheet-manager/issues/113)). Calc can move a
  sheet only by its name, so a move that would need the name of the sheet that does not come
  first is refused, with the two names it confuses. Calc's formulas still find the first of the
  two; renaming one of them avoids that.
- Test with LibreOffice 26.8.2.2 instead of 26.8.1.1 on Linux and Windows. LibreOffice 26.8.2
  fixes Calc's own Duplicate Sheet and Move or Copy Sheet, which in 26.8.0 and 26.8.1 copy
  formulas with relative sheet references incorrectly
  ([tdf#173608](https://bugs.documentfoundation.org/show_bug.cgi?id=173608)); the known issues
  now say so. The list's menu still leaves both commands to Calc's sheet tabs.
- Name each test build's stage in its GitHub release title
  ([#121](https://github.com/viell-dev/slop-calc-sheet-manager/issues/121)): alpha, beta, or
  release candidate, as in `0.1.0 beta (0.0.7)` and `0.1.0 rc (0.0.9)`, where the number in
  brackets is the build's own version. Versions, the **Pre-release** flag, and the update feeds
  work as before, and earlier titles such as `0.1.0 test build (0.0.4)` are unchanged. The
  [releases page](https://viell-dev.github.io/slop-calc-sheet-manager/guide/releases#test-builds)
  explains the stages.
- Check real keyboard and mouse input in a visible Windows window
  ([#114](https://github.com/viell-dev/slop-calc-sheet-manager/issues/114)). A new workflow, not
  yet required for merging, runs the real-input checks on GitHub's hosted Windows Server 2025
  runners: typing and shortcuts in the list, dragging sheets and cancelling with Esc, the menu by
  right click, Menu key and Shift+F10, Rename Sheet and Insert Sheet on the right-clicked row,
  undoing Hide Sheet, and the Rename Sheets dialog. No change to the extension itself.

Install the OXT manually over 0.0.6, restart LibreOffice when asked, and check its SHA-256 asset.
LibreOffice's Extension Manager offers only stable releases, and there is none yet, so later test
builds remain manual downloads. Known limits are in the
[known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues). The next
beta works on keeping the list's selection through Undo and Redo of its own moves
([#91](https://github.com/viell-dev/slop-calc-sheet-manager/issues/91)); the plan towards 0.1.0
is in [#93](https://github.com/viell-dev/slop-calc-sheet-manager/issues/93). A short usability
test on a later beta will be requested before the stable release.

## 0.0.6 - 2026-10-28

Alpha build following 0.0.5, adding batch rename.
Requires LibreOffice 26.2.1 or later with Python support.

- Rename two or more sheets at once
  ([#102](https://github.com/viell-dev/slop-calc-sheet-manager/issues/102)). For several targets,
  the list's context menu offers **Rename Sheets…** in Rename Sheet's place; one sheet keeps
  Calc's own Rename Sheet…. The dialog lists every current and new name, edits the selected row's
  name, and replaces literal, case-sensitive text in every new name with **Replace All**. It
  shows each problem before anything changes: empty names, characters Calc refuses, an
  apostrophe at either end, and names that another sheet has, will have, or that Calc can treat
  as the same. Swaps and cycles of names work. Rename is one undo step; it checks the sheets and
  permissions again before changing a name and reads every rename back. If Calc refuses a name,
  it undoes its own step and checks the old names, or says that it could not. The viewed sheet
  and Calc's selected tabs stay as they were, and the renamed sheets stay picked under their new
  names. Formulas, named ranges and charts follow the new names; sheet names written as text,
  such as in `INDIRECT`, do not change.

Install the OXT manually over 0.0.5, restart LibreOffice when asked, and check its SHA-256 asset.
Later alpha builds remain manual downloads. Known limits, including LibreOffice's own refusal of
some full-width names after a Find & Replace and sheet names written as text, are in the
[known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues). Optional
feedback on the rename dialog and the menu's sheet commands is welcome in
[#117](https://github.com/viell-dev/slop-calc-sheet-manager/issues/117).

## 0.0.5 - 2026-10-28

Alpha build following the 0.0.4 test build.
Requires LibreOffice 26.2.1 or later with Python support.

- Fix Rename Sheet from the list's menu renaming the previously viewed sheet instead of the
  right-clicked or picked one. Its dialog applies to the sheet viewed when confirmed, and Sheet
  Manager restored the earlier view while the dialog was open
  ([#100](https://github.com/viell-dev/slop-calc-sheet-manager/issues/100)). Calc now stays on a
  chosen command's targets, as after its own tab menu, even if its dialog is cancelled.
- Offer **Insert Sheet…**, **Delete Sheet…**, **Rename Sheet…** and **Hide Sheet** directly in
  the list's context menu, replacing **Sheet actions…** and its second, full Calc menu
  ([#101](https://github.com/viell-dev/slop-calc-sheet-manager/issues/101)). Insert and Rename
  act on one sheet; Delete and Hide act on every target. Show Sheet takes Hide's place for hidden
  targets, and the move actions and Help are unchanged. Each command checks its sheets and
  permissions again when it runs, and refuses renamed, replaced or hidden targets, and targets
  that became protected where the command does not allow that (Rename, Delete), without changing
  the view. Opening or closing the menu changes nothing in Calc. If Calc reports an error once a
  command has started, Calc stays on its targets and a message asks you to check them. Duplicate
  Sheet and Move or Copy Sheet stay on Calc's sheet tabs: LibreOffice 26.8.0 and 26.8.1 copy
  relative sheet references wrongly (tdf#173608), and the list moves sheets itself. Calc's sheet
  tabs keep their full menu for every other command.
- Replace the persistent selection-cleared infobar with a ten-second panel notice. Expiration
  keeps keyboard focus, current picks, and Calc's separate grouped-editing warning unchanged.
  Undo/Redo still clears picks conservatively; preserving verified move selections is tracked
  in [#91](https://github.com/viell-dev/slop-calc-sheet-manager/issues/91).
- Drop the guard that **Sheet actions…** placed on Calc's commands while its menu was open. In
  0.0.4 it could be left in place if the panel closed during the menu
  ([#63](https://github.com/viell-dev/slop-calc-sheet-manager/issues/63)); the list's menu now
  drops its pending command instead.
- Describe current development as alpha iteration, with no settled feature scope or scheduled
  stable release. Builds without an agreed stable target are titled with their own version and
  **alpha**, as this one is.

Install the OXT manually over 0.0.4, restart LibreOffice when asked, and check its SHA-256 asset.
LibreOffice's Extension Manager offers only published stable updates, and there is no stable
release yet, so later alpha builds remain manual downloads. Known limits, including conservative
selection clearing on Undo/Redo and LibreOffice's own defect in Duplicate Sheet and Move or Copy
Sheet, are in the
[known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues).

## Unpublished 0.1.0 preparation

This preparation was not published. Development continues in alpha; the earlier stable-release
plan is superseded. Its changes since 0.0.4 were first published in 0.0.5. Requires LibreOffice
26.2.1 or later with Python support.

- Find and select sheets in a vertical sidebar list, with full-width rows, keyboard navigation,
  and an indicator for the viewed sheet. List picks remain independent of Calc's grouped tabs.
- Drag one or more selected sheets any distance, or use Top, Up, Down and Bottom buttons,
  context actions or Alt shortcuts. Each extension move is one undo step, with permission and
  sheet-identity checks before acting and verified recovery if a move fails.
- Open Calc's customized sheet-tab menu through **Sheet actions…**. Wrong-target rename after
  the native dialog is under investigation in
  [#100](https://github.com/viell-dev/slop-calc-sheet-manager/issues/100).

Changes since the 0.0.4 test build:

- Keep new guide instructions marked **Unreleased** through release preparation and failed or
  abandoned publication. Published history controls their availability markers; documentation
  corrections still deploy independently of software versions and tags.
- Release the native sheet-menu dispatch guard even if its panel is disposed while the menu is
  open, so the surviving Calc window can still run ordinary commands after dismissal.
- Replace the persistent selection-cleared infobar with a ten-second panel notice. Expiration
  keeps keyboard focus, current picks, and Calc's separate grouped-editing warning unchanged.
  Undo/Redo still clears picks conservatively; preserving verified move selections is tracked
  in [#91](https://github.com/viell-dev/slop-calc-sheet-manager/issues/91).

Install alpha OXTs manually. LibreOffice's Extension Manager offers only published stable updates;
there is no stable release yet, and the unpublished 0.1.0 preparation will not be published as stable.
Restart LibreOffice when asked. Each release includes an OXT and SHA-256 checksum; test builds remain
manual downloads. See the [guide](https://viell-dev.github.io/slop-calc-sheet-manager/) for use,
compatibility, and known limits, including conservative selection clearing on Undo/Redo.
LibreOffice 26.8.0 and 26.8.1 still have a known formula-reference defect in their own Duplicate
Sheet and Move or Copy Sheet commands; see the guide before using those native copy commands.

## 0.0.4 - 2026-10-26

Third test build for 0.1.0, addressing feedback on 0.0.3.
Requires LibreOffice 26.2.1 or later with Python support.

- Opening the movement context menu keeps the viewed sheet and Calc tab selection unchanged.
  **Sheet actions…** opens Calc's customized menu when every target is visible; only that step
  temporarily targets its native tabs, with safe restoration after dismissal. Mixed visible
  and hidden targets instead offer safe Show/move actions without native grouping.
  Refused rapid repeats also leave the current view and list picks unchanged.
- Restore Top, Up, Down, and Bottom buttons above the list. They share the menu's permission,
  identity and undo checks, show refusal reasons, and support keyboard focus and activation.
  The grouped-editing warning remains a conditional footer.
- Keep row dividers aligned after scrolling and font/DPI changes by following actual native
  row geometry. Decorations stop at the content viewport instead of covering scrollbars, and
  fixed border pixels no longer get copied into rows by native scrolling. Horizontal scrolling
  of long names keeps decorations aligned across the whole viewport.

Install the OXT manually over 0.0.3, restart LibreOffice, and check its SHA-256 asset. Test builds
keep the stable update feed; later test builds remain manual downloads. Existing compatibility
and selection limits remain in the [known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues).

## 0.0.3 - 2026-10-25

Second test build for 0.1.0, focused on the sidebar's interaction and appearance.
Requires LibreOffice 26.2.1 or later with Python support.

- Click anywhere across a row to select it without switching sheets. Double-click or press
  Enter to activate it. Ctrl/Shift selection and keyboard navigation keep an independent range
  anchor through ordinary refreshes.
- Rows have full-width highlights, dividers, and more vertical space. The current-sheet arrow
  and tab-colour square sit separately to the left of the name. Dragging shows a stronger
  three-pixel insertion line with end markers.
- Move sheets from the context menu or with Alt+Home/Up/Down/End. The toolbar is removed, and the
  grouped-editing warning appears in a footer only while multiple Calc tabs are grouped.
- Right-click targets a row without selecting it. It uses the existing picked set when that row
  is already picked. Calc's customized menu is under **Sheet actions**; temporary native tab
  grouping is restored after dismissal where the original sheets can still be proved safe.
- **Sheet Manager Help** opens the project guide. The header's native `?` still opens
  LibreOffice's unavailable local help topic; this host limitation is documented in #81.

Install the OXT manually over 0.0.2 and check its SHA-256 asset. Test builds remain manual
downloads and keep stable updates enabled. Existing compatibility and conservative
selection-clearing limits still apply; see the [known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues).

## 0.0.2 - 2026-10-25

First test build for 0.1.0. This build is intended for testing with synthetic or backed-up
workbooks. It requires LibreOffice 26.2.1 or later with Python support.

- Find every sheet in a vertical sidebar list, with tab colours and active, hidden, protected,
  and scenario states identified.
- Click to activate a sheet, use Ctrl/Shift selection independently of Calc's grouped tabs, and
  navigate or search by typing with the keyboard.
- Move selected sheets by drag and drop or Top, Up, Down, and Bottom buttons, with Alt shortcuts,
  insertion feedback, and edge scrolling. Each extension move is one undo step.
- Follow changes from Calc tabs, menus, macros, other windows, undo and redo. A separate status
  identifies the Calc tabs affected by grouped cell editing.
- Use Calc's own sheet-tab menu for the picked sheets. Hidden-sheet Show and reorder operations
  check permissions, reject stale targets, and verify recovery after a failed operation.
- Install manually from the OXT asset and check its SHA-256 file. Test builds are marked
  **Pre-release**; installed copies keep stable updates enabled and later test builds are manual
  downloads.

Known limits include conservative selection clearing after uncertain structural changes,
full-tree property refresh costs on large workbooks, Ctrl+S moving focus to the sheet, and
native range/cursor limits after a rebuild or a refused held gesture. See
[Compatibility and known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues)
and the [user guide](https://viell-dev.github.io/slop-calc-sheet-manager/) before use.

## Development history before 0.0.2

These notes record implementation and verification work before the first test build; they are
historical development notes, not earlier published releases.

- The list follows this window's selected Calc tabs even when the active sheet does not change.
  A status line identifies grouped Calc tabs separately from independent list picks. Observation
  pauses while the panel is hidden and resumes on reopening, preserving newer list input and
  stale-sheet safeguards ([#5](https://github.com/viell-dev/slop-calc-sheet-manager/issues/5)).
- Added a human release/download page with OXT and checksum links for stable and test builds,
  explained why LibreOffice's version ordering prevents direct SemVer prerelease suffixes, and
  removed the arbitrary `.90` patch reservation in favour of an explicit release flag. Corrected
  outdated feature status in the guide
  ([#73](https://github.com/viell-dev/slop-calc-sheet-manager/issues/73)).
- The release dry run waits for the native CI matrix's full time budget before refusing a build
  whose exact-commit checks have not finished
  ([#72](https://github.com/viell-dev/slop-calc-sheet-manager/issues/72)).
- Cursor restoration now follows the native tree's focused row rather than predicting its position
  from key callbacks. Ordinary rebuilds preserve navigation outside the selection; a refused held
  click restores its picks and, when any survive, returns the cursor to one of them
  ([#69](https://github.com/viell-dev/slop-calc-sheet-manager/issues/69)).
- Move-button enablement no longer consumes a pending ordinary edit notification, which could
  clear the list's picks at the next refresh
  ([#66](https://github.com/viell-dev/slop-calc-sheet-manager/issues/66)).
- Added Top, Up, Down, and Bottom buttons above the list, with Alt+Home/Up/Down/End
  shortcuts, disabled reasons in tooltips, and selection preserved for repeated moves. Each press
  uses the guarded reorder adapter and is one undo step
  ([#35](https://github.com/viell-dev/slop-calc-sheet-manager/issues/35)).
- The reorder adapter now refuses snapshots held across a sheet replacement, even when sheet names
  and retained handle names still match. Snapshots and list views share a document-owned structural
  monitor, and Undo or Redo requires a fresh snapshot
  ([#19](https://github.com/viell-dev/slop-calc-sheet-manager/issues/19)).
- Clean up partial list initialization and failed menu setup, consume owned keys after a handler
  error, and refuse Show Sheet while changes are being recorded. Type-ahead now cycles through
  sheets when their first letter is repeated. The guide and verification map cover the list,
  and optional desktop observations no longer act as a routine release gate.
- Added the sheet list to the panel: every sheet in document order with its tab colour and its
  active, hidden, protected, and scenario state. A click goes to a sheet; Ctrl+click and
  Shift+click select several without changing the active sheet. Selected sheets can be dragged,
  with an insertion line and auto-scroll, to a new place through the reorder layer, in one undo
  step; Esc cancels. Keys typed in the list stay out of the sheet while Calc's shortcuts keep
  working, and the sheet tab menu opens by right click, Menu key, or Shift+F10 for exactly the
  selected sheets ([#2](https://github.com/viell-dev/slop-calc-sheet-manager/issues/2)). A
  renamed sheet leaves the selection, and when sheets may have been added or removed, also by a
  macro that turns off undo or batches its changes, the list clears its selection and says so,
  rather than act on a sheet that was not selected
  ([#28](https://github.com/viell-dev/slop-calc-sheet-manager/issues/28)); a click ends any
  grouping of Calc's tabs ([#25](https://github.com/viell-dev/slop-calc-sheet-manager/issues/25));
  Calc no longer hangs when the list schedules a refresh during a change
  ([#55](https://github.com/viell-dev/slop-calc-sheet-manager/issues/55));
  showing hidden sheets needs undo and is undone on failure
  ([#27](https://github.com/viell-dev/slop-calc-sheet-manager/issues/27)); refreshing keeps the
  keyboard position ([#29](https://github.com/viell-dev/slop-calc-sheet-manager/issues/29)).
- Added real-input UI tests with gtk3 and gen, headless sheet list checks, and a manual checklist
  with a synthetic workbook for what automation cannot reach.
- Added checked release publication with versioned OXT/checksum assets, a read-only dry run, and
  stable/prerelease update feeds on GitHub Pages. Installed copies use the stable feed. No build
  has been published yet ([#6](https://github.com/viell-dev/slop-calc-sheet-manager/issues/6)).
- Added the reorder operation layer for drag/drop and Top, Up, Down, and Bottom: minimum-call
  planning, scenario blocks, permission checks, one undo step, and verified failure recovery.
  The sheet list's drag and drop uses it.
  Planning stays responsive in large workbooks; recovery preserves the user's previous action at a full
  undo stack, and view-restoration failures warn without undoing a verified move. Both success and
  rollback restore the view before unlocking controllers to avoid an intermediate repaint. Balanced groups
  work around Calc's undo-capacity defect
  ([#16](https://github.com/viell-dev/slop-calc-sheet-manager/issues/16)); embedded chart names
  retain Calc's native rename-on-move limitation
  ([#17](https://github.com/viell-dev/slop-calc-sheet-manager/issues/17)).
- Added an empty Sheet Manager deck to Calc's sidebar as the foundation for the sheet list.
- Fixed a crash when Shift, Ctrl, or Alt was pressed in Calc while the Sheet Manager deck was
  shown ([#18](https://github.com/viell-dev/slop-calc-sheet-manager/issues/18)).
- Added Windows development checks, durable LibreOffice download pins, and integration checks that
  reject crashes or fatal-error logs during shutdown.
- Avoided an intermittent LibreOffice crash in painted integration sessions by waiting a second
  before the tests close Writer ([#8](https://github.com/viell-dev/slop-calc-sheet-manager/issues/8),
  [#30](https://github.com/viell-dev/slop-calc-sheet-manager/issues/30)).
- Kept automatic dependency updates for the checks container on Python 3.12, the oldest supported
  version, and on the Node major version that CI uses.
- Added `.nvmrc`, so that nvm and fnm select the Node version CI uses for Pyright. The workflows
  install Node from it, and a unit test keeps it equal to the checks image's Node.
- Made the integration resize test use observed frame dimensions across gtk3 window layouts,
  retaining the exact 150-pixel frame and panel growth checks
  ([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)).
- Split required Linux headless checks from non-required painted gtk3 jobs, added a manual soak
  with extension-free controls and crash backtraces, and extended the shutdown grace period to
  30 seconds. Image reuse now rebuilds for changed Dockerfiles or pins, and the checks image
  excludes unrelated build context ([#10](https://github.com/viell-dev/slop-calc-sheet-manager/issues/10)).
- Wait for two stable frame/panel measurements before the resize baseline, retaining exact
  150-pixel growth checks ([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)).
- Keep diagnostic files separate for each integration session, clear stale runner artifacts, and
  continue soak measurements after missing or unreadable session results. Manual soaks use their
  own workflow, avoiding skipped checks with required job names.
- Asked contributors to say when an AI agent wrote or submitted an issue, pull request, or comment,
  and whether a person reviewed it.
- Required the painted gtk3 checks for merging again, after 180 painted sessions on `main` ran
  without a failure ([#32](https://github.com/viell-dev/slop-calc-sheet-manager/issues/32)).
- Added issue forms for bug reports, improvements, feature requests, and questions. The bug form
  asks for LibreOffice's copied version information, how LibreOffice was installed, and a workbook
  made for the report. The README now says which LibreOffice versions and environments are
  verified, expected to work, or unsupported
  ([#56](https://github.com/viell-dev/slop-calc-sheet-manager/issues/56)).
- Made the integration checks fail visibly instead of passing or hanging:
  - They keep LibreOffice's crash dumps, and fail a session whose office crashed even though it
    exited with status 0 on Windows
    ([#48](https://github.com/viell-dev/slop-calc-sheet-manager/issues/48)).
  - On Windows they close test workbooks on LibreOffice's main thread
    ([#47](https://github.com/viell-dev/slop-calc-sheet-manager/issues/47)).
  - They stop an office whose callback or terminate request stalls
    ([#50](https://github.com/viell-dev/slop-calc-sheet-manager/issues/50),
    [#40](https://github.com/viell-dev/slop-calc-sheet-manager/issues/40)).
  - They repeat the painted resize check's setup when the new window is maximized late
    ([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)).
- Added a user guide at <https://viell-dev.github.io/slop-calc-sheet-manager/>, published with the
  update feeds. It covers installation, updates, removal, use, compatibility, troubleshooting, and
  reporting a problem, and says which version it describes. The page listing the feeds moved to
  `updates/`; the feed addresses are unchanged
  ([#56](https://github.com/viell-dev/slop-calc-sheet-manager/issues/56)).
- Checked that LibreOffice still converts files headlessly with the extension installed, and that
  removing the extension leaves no deck, panel, or installed copy behind. `docs/verification.md`
  maps each promise to the checks that verify it.

## 0.0.1 - Development baseline (unpublished)

- Initial development package for release-process dry runs. This is not a published release;
  the first feature release is planned as 0.1.0.
