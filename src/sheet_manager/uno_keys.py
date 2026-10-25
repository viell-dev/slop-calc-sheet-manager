"""Keep keys typed in the sheet list out of the sheet, without disturbing other windows.

UNO key listeners cannot consume a key, so the list registers a toolkit key handler while a
panel control has focus. The handler sees every key in the application first; it acts only when
the list's tree has focus at that moment, and routes keys as ``sheet_manager.keys``
describes. Shortcuts are resolved through the document's, Calc's, and the global shortcut
configuration, in the order LibreOffice itself uses, and dispatched to the panel's frame.
"""

import unohelper
from com.sun.star.awt import KeyEvent, XKeyHandler
from com.sun.star.container import NoSuchElementException

from sheet_manager.keys import (
    SHIFT,
    TAB,
    KeyRoute,
    move_action,
    route_key,
    unbound_route,
)
from sheet_manager.uno_calc import report

CALC_MODULE = "com.sun.star.sheet.SpreadsheetDocument"


class Shortcuts:
    def __init__(self, context, document):
        self._context = context
        self._document = document
        self._configurations = None

    def _load(self):
        configurations = []
        manager = self._context.ServiceManager
        loaders = (
            lambda: self._document.getUIConfigurationManager().getShortCutManager(),
            lambda: (
                manager.createInstanceWithContext(
                    "com.sun.star.ui.ModuleUIConfigurationManagerSupplier", self._context
                )
                .getUIConfigurationManager(CALC_MODULE)
                .getShortCutManager()
            ),
            lambda: manager.createInstanceWithContext(
                "com.sun.star.ui.GlobalAcceleratorConfiguration", self._context
            ),
        )
        for load in loaders:
            try:
                configuration = load()
            except Exception:
                report("loading a shortcut configuration")
                continue
            if configuration is not None:
                configurations.append(configuration)
        return configurations

    def command(self, code: int, modifiers: int) -> str:
        if self._configurations is None:
            self._configurations = self._load()
        key = KeyEvent()
        key.KeyCode, key.Modifiers = code, modifiers
        for configuration in self._configurations:
            try:
                return configuration.getCommandByKeyEvent(key)
            except NoSuchElementException:
                continue
        return ""


class ListKeyHandler(unohelper.Base, XKeyHandler):
    """Registered while a panel control has focus; checks that again for every key."""

    def __init__(self, sheet_list, shortcuts: Shortcuts):
        self._list = sheet_list
        self._shortcuts = shortcuts
        self._consumed: dict[int, bool] = {}

    def keyPressed(self, event):
        owned = False
        try:
            if not self._list.owns_keys():
                return False
            owned = True
            # PyUNO passes a UNO char as uno.Char; its value is the one-character string.
            char = getattr(event.KeyChar, "value", event.KeyChar)
            route = route_key(event.KeyCode, event.Modifiers, char)
            if (
                event.KeyCode == TAB
                and event.Modifiers in (0, SHIFT)
                and self._list.travel_focus(event.Modifiers == SHIFT)
            ):
                route = KeyRoute.IGNORE  # The panel posted its focus step.
            if route is KeyRoute.TREE:
                self._list.tree_key(event.KeyCode, event.Modifiers)
            elif route is KeyRoute.SHORTCUT:
                command = self._shortcuts.command(event.KeyCode, event.Modifiers)
                if command:
                    self._list.run_command(command)
                else:
                    route = unbound_route(event.Modifiers)
            elif route is KeyRoute.ACTIVATE:
                self._list.queue_input(self._list.activate_selection, "activating a sheet")
            elif route is KeyRoute.TYPE_AHEAD:
                self._list.queue_input(lambda: self._list.type_ahead(char), "type-ahead")
            elif route is KeyRoute.MENU:
                self._list.queue_input(self._list.open_menu_for_keyboard, "the sheet tab menu")
            elif route is KeyRoute.MOVE:
                self._list.queue_move(move_action(event.KeyCode, event.Modifiers))
            self._consumed[event.KeyCode] = route.consumed
            return route.consumed
        except Exception:
            report("the key handler")
            if owned:
                self._consumed[event.KeyCode] = True
            return owned

    def keyReleased(self, event):
        # Consume the release of a press that was consumed, wherever the focus is now.
        return self._consumed.pop(event.KeyCode, False)

    def disposing(self, event):
        pass
