"""Visible native move buttons; selection, planning and execution stay in the list.

This module owns the four controls above the list: their names, sizing, and refusal tooltips.
The footer stays separate, in `uno_status`.

- Enablement reads the structure monitor's generation without consuming undo or modify evidence.
- Keyboard activation stamps input before native button handling, and queued focus requests
  reject newer input too.
- Tab follows the visible button and list order and skips disabled controls. Native Enter and
  Space activate a button, while letters stay out of cells.
- Alt+Home, Alt+Up, Alt+Down and Alt+End stay local to the focused list or move button, and a
  move returns focus to the tree.
"""

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
        self._states = None
        self._help = {
            "top": tr("Move selected sheets to the top (Alt+Home)."),
            "up": tr("Move selected sheets up one place (Alt+Up)."),
            "down": tr("Move selected sheets down one place (Alt+Down)."),
            "bottom": tr("Move selected sheets to the bottom (Alt+End)."),
        }
        sizes = []
        try:
            manager = context.ServiceManager
            for action, label in zip(
                ACTIONS, (tr("Top"), tr("Up"), tr("Down"), tr("Bottom")), strict=True
            ):
                model = manager.createInstanceWithContext(
                    "com.sun.star.awt.UnoControlButtonModel", context
                )
                model.Label, model.HelpText = label, self._help[action]
                model.Tabstop, model.Enabled = True, False
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
        except BaseException:
            self.dispose()
            raise
        self.height = max(size.Height for size in sizes) + 8
        self.minimum_width = 4 * max(size.Width for size in sizes) + 20

    def set_bounds(self, width):
        usable = max(width - 20, 0)
        for index, button in enumerate(self.buttons.values()):
            left, right = usable * index // 4, usable * (index + 1) // 4
            button.setPosSize(4 + left + 4 * index, 4, right - left, self.height - 8, 15)

    def update(self, states):
        if states == self._states:
            return
        for action, button in self.buttons.items():
            state, model = states[action], button.getModel()
            model.HelpText = self._help[action] + (" " + state.reason if not state.allowed else "")
            model.Enabled = state.allowed
        self._states = states

    def has_focus(self):
        return any(button.getPeer().hasFocus() for button in self.buttons.values())

    def actionPerformed(self, event):
        self._request(str(event.ActionCommand))

    def mousePressed(self, event):
        if event.Buttons & 1:
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
