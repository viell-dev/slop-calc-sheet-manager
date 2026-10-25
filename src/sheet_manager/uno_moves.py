"""Native move controls and Calc tab status. Planning and identity belong to the sheet list."""

import contextlib

import unohelper
from com.sun.star.awt import XActionListener, XMouseListener

from sheet_manager.i18n import tr

ACTIONS = ("top", "up", "down", "bottom")


class MoveButtons(unohelper.Base, XActionListener, XMouseListener):
    def __init__(self, context, parent, request, focus, note_input):
        self._request = request
        self._note_input = note_input
        self._cleanup = contextlib.ExitStack()
        self.buttons = {}
        self._tabs = None
        self._help = {
            "top": tr("Move selected sheets to the top (Alt+Home)."),
            "up": tr("Move selected sheets up one place (Alt+Up)."),
            "down": tr("Move selected sheets down one place (Alt+Down)."),
            "bottom": tr("Move selected sheets to the bottom (Alt+End)."),
        }
        labels = (tr("Top"), tr("Up"), tr("Down"), tr("Bottom"))
        sizes = []
        try:
            manager = context.ServiceManager
            for action, label in zip(ACTIONS, labels, strict=True):
                model = manager.createInstanceWithContext(
                    "com.sun.star.awt.UnoControlButtonModel", context
                )
                model.Label, model.HelpText = label, self._help[action]
                model.Tabstop = True
                model.Enabled = False
                button = manager.createInstanceWithContext(
                    "com.sun.star.awt.UnoControlButton", context
                )
                self._cleanup.callback(button.dispose)
                button.setModel(model)
                button.createPeer(parent.getToolkit(), parent)
                button.setActionCommand(action)
                button.addActionListener(self)
                button.addFocusListener(focus)
                button.addMouseListener(self)
                self.buttons[action] = button
                sizes.append(button.getMinimumSize())
            model = manager.createInstanceWithContext(
                "com.sun.star.awt.UnoControlFixedTextModel", context
            )
            model.MultiLine = True
            self._status = manager.createInstanceWithContext(
                "com.sun.star.awt.UnoControlFixedText", context
            )
            self._cleanup.callback(self._status.dispose)
            self._status.setModel(model)
            self._status.createPeer(parent.getToolkit(), parent)
            self._status_height = 2 * max(16, self._status.getMinimumSize().Height) + 4
        except BaseException:
            self.dispose()
            raise
        self._button_height = max(size.Height for size in sizes) + 8
        self.height = self._status_height + self._button_height
        self.minimum_width = 4 * max(size.Width for size in sizes) + 20

    def set_bounds(self, width):
        self._status.setPosSize(4, 2, max(width - 8, 0), self._status_height - 4, 15)
        usable = max(width - 20, 0)
        for index, button in enumerate(self.buttons.values()):
            left, right = usable * index // 4, usable * (index + 1) // 4
            button.setPosSize(
                4 + left + 4 * index,
                self._status_height + 4,
                right - left,
                self._button_height - 8,
                15,
            )

    def show_tabs(self, names):
        """Show Calc's native tabs separately from the list's independent picks."""
        names = tuple(names)
        if names == self._tabs:
            return
        self._tabs = names
        joined = ", ".join(names)
        if len(names) > 1:
            label = tr("Edits affect {count} Calc tabs: {names}").format(
                count=len(names), names=joined
            )
            help_text = tr(
                "These Calc tabs are grouped: {names}. Cell edits affect every grouped tab. "
                "The sheet list's picks are separate."
            ).format(names=joined)
        else:
            label = tr("Calc tab: {name}").format(name=joined)
            help_text = tr("The sheet list's picks can differ from Calc's selected tabs.")
        model = self._status.getModel()
        model.Label, model.HelpText = label, help_text

    def update(self, states):
        for action, button in self.buttons.items():
            state = states[action]
            model = button.getModel()
            model.HelpText = self._help[action] + (" " + state.reason if not state.allowed else "")
            model.Enabled = state.allowed

    def has_focus(self):
        return any(button.getPeer().hasFocus() for button in self.buttons.values())

    def actionPerformed(self, event):
        self._request(str(event.ActionCommand))  # Only captures state and posts work.

    def mousePressed(self, event):
        if event.Buttons & 1:  # Native left-button activation precedes actionPerformed.
            self._note_input()

    def mouseReleased(self, event):
        if event.Buttons & 1:
            self._note_input()

    def mouseEntered(self, event):
        pass

    def mouseExited(self, event):
        pass

    def dispose(self):
        self._cleanup.close()

    def disposing(self, event):
        pass
