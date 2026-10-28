"""The Rename Sheets dialog: proposed names for the chosen sheets, edited before anything changes.

A modal dialog over the document window, built from UNO toolkit models. It lists every target as
its current name and its proposed one (`rename.row_label`), with each problem beside the row it
belongs to. A field edits the selected row's proposal; Find, Replace with and Replace All change
every proposal with literal, case-sensitive text, as often as needed; Reset All starts again.
Rename is enabled only when at least one name changes and nothing is wrong, and before closing it
asks `check` (the adapter's preflight) again, showing any refusal in the status line. The
document is changed only after the dialog has closed, by the caller.

- No button is the default: Enter in the Find field must not rename a batch whose replacement
  has not been made yet. Every control has a mnemonic, Tab follows the layout, and Esc cancels.
- The control listeners only post work through `uno_calc.MainThread`, which runs it in the
  dialog's own event loop, in the order the input came: an edit queued before a click on Rename
  or on another row is taken first, for the row it was typed in. Work posted after the dialog
  closed is dropped.
- Setting the field's text for a newly selected row reports a text change too; it changes no
  proposal, because the text equals the row's proposal already.
- Rows are written in bulk when many change at once (Replace All): replacing list box items one
  at a time was slow through UNO, measured with 1,000 items (#102).
"""

from collections.abc import Callable
from typing import Any

import unohelper
from com.sun.star.awt import XActionListener, XItemListener, XTextListener

from sheet_manager.i18n import tr
from sheet_manager.rename import Batch, Plan, quoted, row_label, summary
from sheet_manager.uno_calc import MainThread

CANCEL = 2  # com.sun.star.awt.PushButtonType.CANCEL: closes the dialog without a result.
FEW_ROWS = 8  # Up to this many changed rows are replaced one by one, keeping the scroll position.


class _Post(unohelper.Base, XTextListener, XItemListener, XActionListener):
    """A control listener that only posts its work to the main thread."""

    def __init__(self, owner: "RenameDialog", work: Callable[[], None], where: str):
        self._owner = owner
        self._work = work
        self._where = where

    def textChanged(self, rEvent: Any) -> None:
        self._owner.post(self._work, self._where)

    def itemStateChanged(self, rEvent: Any) -> None:
        self._owner.post(self._work, self._where)

    def actionPerformed(self, rEvent: Any) -> None:
        self._owner.post(self._work, self._where)

    def disposing(self, Source: Any) -> None:
        pass


class RenameDialog:
    def __init__(self, context: Any, parent: Any, batch: Batch, check: Callable[[Plan], str]):
        self._context = context
        self._parent = parent
        self._batch = batch
        self._check = check
        self._main = MainThread(context)
        self._closed = False
        self._pending: set[str] = set()
        self._row = 0
        self._labels: list[str] = []
        self._result: Plan | None = None
        self._dialog: Any = None

    def post(self, work: Callable[[], None], where: str) -> None:
        """Queue work once until it runs; nothing runs after the dialog closed."""
        if self._closed or where in self._pending:
            return
        self._pending.add(where)

        def run() -> None:
            self._pending.discard(where)
            if not self._closed:
                work()

        self._main.post(run, where)

    def run(self) -> Plan | None:
        """Show the dialog until Rename or Cancel; the plan to apply, or None."""
        self._dialog = self._build()
        try:
            self._show_row()
            self._update()
            self._dialog.execute()
        finally:
            self._closed = True
            self._main.closed = True
            self._dialog.dispose()
        return self._result

    # Building

    def _build(self) -> Any:
        manager = self._context.ServiceManager
        model = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialogModel", self._context
        )
        model.Title = tr("Rename Sheets")
        model.Width, model.Height = 280, 236
        add = self._adder(model)
        add("FixedText", "find_label", 8, 8, 64, 10, Label=tr("~Find:"))
        add("Edit", "find", 76, 6, 134, 13, HelpText=tr("Text to find in the new names."))
        add("FixedText", "replace_label", 8, 24, 64, 10, Label=tr("Re~place with:"))
        add(
            "Edit",
            "replace",
            76,
            22,
            134,
            13,
            HelpText=tr("Text that replaces it. Leave it empty to remove the text."),
        )
        add(
            "Button",
            "replace_all",
            216,
            21,
            56,
            15,
            Label=tr("Replace ~All"),
            HelpText=tr("Replace the text in every new name. Matches are exact, case included."),
        )
        add("FixedText", "list_label", 8, 44, 264, 10, Label=tr("~Sheets:"))
        add(
            "ListBox",
            "rows",
            8,
            56,
            264,
            110,
            Dropdown=False,
            MultiSelection=False,
            StringItemList=(),
        )
        add("FixedText", "name_label", 8, 174, 64, 10, Label=tr("~New name:"))
        add("Edit", "name", 76, 172, 196, 13, HelpText=tr("The selected sheet's new name."))
        add("FixedText", "status", 8, 190, 264, 20, Label="", MultiLine=True)
        add(
            "Button",
            "reset",
            8,
            214,
            56,
            15,
            Label=tr("R~eset All"),
            HelpText=tr("Put back every sheet's current name."),
        )
        add("Button", "rename", 150, 214, 58, 15, Label=tr("~Rename"), Enabled=False)
        add("Button", "cancel", 214, 214, 58, 15, Label=tr("Cancel"), PushButtonType=CANCEL)
        dialog = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialog", self._context
        )
        try:
            dialog.setModel(model)
            toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", self._context)
            dialog.createPeer(toolkit, self._parent)
            dialog.getControl("name").addTextListener(_Post(self, self._edited, "edit"))
            dialog.getControl("rows").addItemListener(_Post(self, self._selected, "row"))
            for name, work in (
                ("replace_all", self._replace),
                ("reset", self._reset),
                ("rename", self._rename),
            ):
                dialog.getControl(name).addActionListener(_Post(self, work, name))
        except BaseException:
            dialog.dispose()
            raise
        return dialog

    @staticmethod
    def _adder(model: Any) -> Callable[..., None]:
        def add(kind: str, name: str, x: int, y: int, width: int, height: int, **values: Any):
            control = model.createInstance(f"com.sun.star.awt.UnoControl{kind}Model")
            control.Name = name
            control.PositionX, control.PositionY, control.Width, control.Height = (
                x,
                y,
                width,
                height,
            )
            for key, value in values.items():
                setattr(control, key, value)
            model.insertByName(name, control)

        return add

    def _control(self, name: str) -> Any:
        return self._dialog.getControl(name)

    # Posted work

    def _show_row(self) -> None:
        """Put the selected row's proposal in the field; changes no proposal."""
        self._control("name").setText(self._batch.proposals[self._row])

    def _edited(self) -> None:
        text = self._control("name").getText()
        if text != self._batch.proposals[self._row]:
            self._batch.set(self._row, text)
            self._update()

    def _selected(self) -> None:
        row = self._control("rows").getSelectedItemPos()
        if row < 0 or row == self._row:
            return
        self._row = row
        self._show_row()
        self._update()

    def _replace(self) -> None:
        find = self._control("find").getText()
        if not find:
            self._update(tr("Type the text to find first."))
            return
        changed = self._batch.replace_all(find, self._control("replace").getText())
        self._show_row()
        if changed:
            self._update()
        else:
            self._update(tr("No new name contains {text}.").format(text=quoted(find)))

    def _reset(self) -> None:
        self._batch.reset()
        self._show_row()
        self._update()

    def _rename(self) -> None:
        try:
            plan = self._batch.plan()
        except ValueError as error:
            self._update(str(error))
            return
        reason = self._check(plan)
        if reason:
            self._update(reason)
            return
        self._result = plan
        self._dialog.endExecute()

    # Showing the state

    def _update(self, note: str = "") -> None:
        found = self._batch.problems()
        labels = [
            row_label(old, new, reason)
            for (old, new), reason in zip(self._batch.renames(), found, strict=True)
        ]
        self._write_rows(labels)
        status = note or found[self._row] or summary(self._batch, found)
        self._control("status").getModel().Label = status
        valid = bool(self._batch.changes()) and not any(found)
        self._control("rename").getModel().Enabled = valid

    def _write_rows(self, labels: list[str]) -> None:
        rows = self._control("rows")
        changed = [
            index
            for index, label in enumerate(labels)
            if index >= len(self._labels) or self._labels[index] != label
        ]
        if not changed:
            return
        if len(self._labels) == len(labels) and len(changed) <= FEW_ROWS:
            for index in changed:
                rows.removeItems(index, 1)
                rows.addItem(labels[index], index)
        else:
            rows.getModel().StringItemList = tuple(labels)
        self._labels = labels
        rows.selectItemPos(self._row, True)
        rows.makeVisible(self._row)
