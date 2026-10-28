"""Separate footer messages for grouped editing and transient selection clearing.

One label warns while several Calc tabs are grouped; the other shows the list's transient notice
that its picks were cleared. The notice expiring leaves the group warning intact. Native adjusted
text sizing follows the available width, and height changes below the tree keep its row origin.
"""

from com.sun.star.awt import Size

from sheet_manager.i18n import tr


class CalcStatus:
    def __init__(self, context, parent):
        self._control = _text_control(context, parent)
        try:
            self._notice_control = _text_control(context, parent)
            self._height = 2 * max(16, self._control.getMinimumSize().Height) + 8
            self._tabs = ()
            self._notice = False
            self._notice_height = 0
            self._control.getModel().HelpText = tr(
                "Cell edits affect every grouped Calc tab. The sheet list's picks are separate."
            )
            self._notice_control.getModel().HelpText = tr(
                "Why the sheet list's selection was cleared. Disappears after ten seconds."
            )
        except BaseException:
            self.dispose()
            raise

    @property
    def height(self):
        return (self._height if len(self._tabs) > 1 else 0) + self._notice_height

    def set_bounds(self, width, height):
        width = max(1, width - 8)
        self._notice_height = (
            self._notice_control.calcAdjustedSize(Size(width, 0)).Height + 8 if self._notice else 0
        )
        self._control.setPosSize(
            4, max(0, height - self.height), width, self.height - self._notice_height, 15
        )
        self._notice_control.setPosSize(
            4, max(0, height - self._notice_height), width, self._notice_height, 15
        )

    def show_notice(self, visible):
        self._notice = visible
        self._notice_control.getModel().Label = (
            tr("Selection cleared after a sheet change or Undo/Redo. Select sheets again.")
            if visible
            else ""
        )
        self._notice_control.setVisible(visible)

    def show_tabs(self, names):
        names = tuple(names)
        if names == self._tabs:
            return False
        self._tabs = names
        grouped = len(names) > 1
        self._control.getModel().Label = (
            tr("Edits affect {count} Calc tabs: {names}").format(
                count=len(names), names=", ".join(names)
            )
            if grouped
            else ""
        )
        self._control.setVisible(grouped)
        return True

    def dispose(self):
        try:
            if hasattr(self, "_notice_control"):
                self._notice_control.dispose()
        finally:
            self._control.dispose()


def _text_control(context, parent):
    manager = context.ServiceManager
    model = manager.createInstanceWithContext("com.sun.star.awt.UnoControlFixedTextModel", context)
    model.MultiLine = True
    control = manager.createInstanceWithContext("com.sun.star.awt.UnoControlFixedText", context)
    try:
        control.setModel(model)
        control.createPeer(parent.getToolkit(), parent)
        control.setVisible(False)
    except BaseException:
        control.dispose()
        raise
    return control
