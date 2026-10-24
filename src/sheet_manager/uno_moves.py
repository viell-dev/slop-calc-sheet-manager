"""Native move buttons. Planning, identity checks, and execution belong to the sheet list."""

import contextlib

import unohelper
from com.sun.star.awt import XActionListener

from sheet_manager.i18n import tr

ACTIONS = ("top", "up", "down", "bottom")


class MoveButtons(unohelper.Base, XActionListener):
    def __init__(self, context, parent, request, focus):
        self._request = request
        self._cleanup = contextlib.ExitStack()
        self.buttons = {}
        self._help = {
            "top": tr("Move selected sheets to the top (Alt+Shift+Home)."),
            "up": tr("Move selected sheets up one place (Alt+Shift+Up)."),
            "down": tr("Move selected sheets down one place (Alt+Shift+Down)."),
            "bottom": tr("Move selected sheets to the bottom (Alt+Shift+End)."),
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
                self.buttons[action] = button
                sizes.append(button.getMinimumSize())
        except BaseException:
            self.dispose()
            raise
        self.height = max(size.Height for size in sizes) + 8
        self.minimum_width = sum(size.Width for size in sizes) + 20

    def set_bounds(self, width):
        usable = max(width - 20, 0)
        for index, button in enumerate(self.buttons.values()):
            left, right = usable * index // 4, usable * (index + 1) // 4
            button.setPosSize(4 + left + 4 * index, 4, right - left, self.height - 8, 15)

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

    def dispose(self):
        self._cleanup.close()

    def disposing(self, event):
        pass
