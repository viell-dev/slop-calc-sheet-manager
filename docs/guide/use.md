# Use the deck

The development version adds a **Sheet Manager** deck to Calc's sidebar. The deck is empty: the
sheet list that will fill it is still being built (see [Status and plans](./status.md)).

## Open it

1. Open a workbook in Calc. The deck exists only in Calc, not in Writer or other applications.
2. Show the sidebar with **View ▸ Sidebar**. In Calc, the shortcut is Ctrl+F5.
3. Select **Sheet Manager** in the sidebar's tab bar, the column of icons along its edge.

The deck is also shown for workbooks opened read-only. It follows the sidebar when you resize,
dock, or undock it, and it closes with its workbook.

## Keyboard

The deck has no controls or shortcuts of its own yet, so nothing in it reacts to keys. LibreOffice's
own keyboard access to the sidebar works as usual. You can press Shift, Ctrl, and Alt while the deck
is shown: an earlier version crashed LibreOffice when you did, and a test now presses these keys
in a real window on every change.

The planned sheet list is to be fully usable from the keyboard, and keys used in the list are not
to reach the sheet. [Status and plans](./status.md) lists what 0.1.0 is planned to include.

## What it does not do

The development version does not read, change, save, or close your workbooks. It makes no network
requests. LibreOffice checks the project's update feed only when you ask it to check for updates.
