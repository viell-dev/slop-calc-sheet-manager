"""A footer only while cell edits would affect several grouped Calc tabs."""

from sheet_manager.i18n import tr


class CalcStatus:
    def __init__(self, context, parent):
        manager = context.ServiceManager
        model = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlFixedTextModel", context
        )
        model.MultiLine = True
        self._control = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlFixedText", context
        )
        try:
            self._control.setModel(model)
            self._control.createPeer(parent.getToolkit(), parent)
            self._height = 2 * max(16, self._control.getMinimumSize().Height) + 8
            self._tabs = ()
            self.height = 0
            self._control.setVisible(False)
        except BaseException:
            self._control.dispose()
            raise

    def set_bounds(self, width, height):
        self._control.setPosSize(
            4, max(0, height - self.height), max(0, width - 8), self.height, 15
        )

    def show_tabs(self, names):
        names = tuple(names)
        if names == self._tabs:
            return False
        self._tabs = names
        self.height = self._height if len(names) > 1 else 0
        model = self._control.getModel()
        model.Label = (
            tr("Edits affect {count} Calc tabs: {names}").format(
                count=len(names), names=", ".join(names)
            )
            if self.height
            else ""
        )
        model.HelpText = tr(
            "Cell edits affect every grouped Calc tab. The sheet list's picks are separate."
        )
        self._control.setVisible(bool(self.height))
        return True

    def dispose(self):
        self._control.dispose()
