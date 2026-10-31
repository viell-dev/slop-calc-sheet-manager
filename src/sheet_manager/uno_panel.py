"""UNO sidebar adapter: the panel factory and the panel that holds the sheet list.

The panel's window is a plain `"window"` peer that holds the list's controls directly. Its
accessible context lists them as children, so a screen reader, or the gtk3 bridge tracking focus,
reaches them by walking down from the sidebar (#133). Behind them lies a disabled plain
`"window"` of the panel's size, the backdrop: VCL swallows a mouse press on a disabled window,
whereas an enabled plain window leaves it unhandled and VCL takes a press in the panel's margins
as the start of undocking the sidebar (measured with the `win` interface; gtk3's embedded sidebar
does not undock). VCL hit-tests children in creation order, so the backdrop is created after the
list's controls and lies below them; create every control before it.

Until #133 the panel was a page-less tab control, which consumes presses but whose accessible
context lists only tabs, so its children were unreachable. It also crashed VCL's access-key walk on
every Shift, Ctrl, or Alt change (#18, #31) unless it sat inside a plain window. Keep any
page-less tab control out of the window tree; keep the integration accessibility walk, the
margin-press checks and the painted modifier-key test; and keep the panel filling its container on
resize.
"""

from contextlib import suppress
from typing import cast

import uno
import unohelper
from com.sun.star.awt import Rectangle, WindowDescriptor, XWindowListener
from com.sun.star.container import NoSuchElementException
from com.sun.star.lang import EventObject, XComponent, XServiceInfo
from com.sun.star.ui import LayoutSize, XSidebarPanel, XToolPanel, XUIElement, XUIElementFactory

from sheet_manager.uno_calc import report
from sheet_manager.uno_list import SheetList

FACTORY = "dev.viell.sheetmanager.PanelFactory"
RESOURCE_URL = "private:resource/toolpanel/SheetManager/Panel"
TOOLPANEL = cast(int, uno.getConstantByName("com.sun.star.ui.UIElementType.TOOLPANEL"))
SHOW = cast(int, uno.getConstantByName("com.sun.star.awt.WindowAttribute.SHOW"))
POSSIZE = cast(int, uno.getConstantByName("com.sun.star.awt.PosSize.POSSIZE"))


def _create_window(toolkit, service, parent, bounds):
    """Create a shown child peer filling its parent's current size."""
    descriptor = WindowDescriptor()
    descriptor.Type = uno.Enum("com.sun.star.awt.WindowClass", "CONTAINER")
    descriptor.WindowServiceName = service
    descriptor.ParentIndex = -1
    descriptor.Parent = parent
    descriptor.Bounds = Rectangle(0, 0, bounds.Width, bounds.Height)
    descriptor.WindowAttributes = SHOW
    return toolkit.createWindow(descriptor)


class SheetPanel(
    unohelper.Base, XUIElement, XToolPanel, XSidebarPanel, XComponent, XWindowListener
):
    """A plain window, sized by the sidebar's panel container, holding the sheet list's controls
    over a disabled backdrop."""

    def __init__(self, context, resource_url, arguments):
        self.ResourceURL = resource_url
        self.Type = TOOLPANEL
        self.Frame = arguments["Frame"]
        self._parent = arguments["ParentWindow"]
        self._listeners = []
        self._disposed = False
        bounds = self._parent.getPosSize()
        toolkit = self._parent.getToolkit()
        # The controls are the window's own children, so that its accessible context lists them.
        self.Window = _create_window(toolkit, "window", self._parent, bounds)
        self.list = None
        try:
            self.list = SheetList(context, self.Frame, self.Window)
            self.list.set_bounds(bounds.Width, bounds.Height)
        except Exception:
            if self.list is not None:
                with suppress(Exception):
                    self.list.dispose()
                self.list = None
            # An empty panel is better than a sidebar that fails to open.
            report("creating the sheet list")
        # An enabled plain window leaves a press unhandled, and VCL starts undocking the sidebar;
        # a disabled one swallows it. Created last, so that it lies below every control.
        self._backdrop = _create_window(toolkit, "window", self.Window, bounds)
        self._backdrop.setEnable(False)
        self._parent.addWindowListener(self)

    def getRealInterface(self):
        return self

    def createAccessible(self, parent_accessible):
        # The tree control provides its own accessible rows. A native peer is an XWindow,
        # not an XAccessible; do not return it as the wrong UNO interface.
        return None

    def getHeightForWidth(self, width):
        return LayoutSize(0, -1, 400)

    def getMinimalWidth(self):
        return self.list.minimal_width if self.list is not None else 150

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._parent.removeWindowListener(self)
        if self.list is not None:
            try:
                self.list.dispose()
            except Exception:
                report("disposing the sheet list")
        self._backdrop.dispose()
        self.Window.dispose()
        listeners, self._listeners = self._listeners, []
        for listener in listeners:
            listener.disposing(EventObject(self))

    def addEventListener(self, listener):
        if self._disposed:
            listener.disposing(EventObject(self))
        elif listener not in self._listeners:
            self._listeners.append(listener)

    def removeEventListener(self, listener):
        if listener in self._listeners:
            self._listeners.remove(listener)

    def windowResized(self, event):
        if not self._disposed:
            self.Window.setPosSize(0, 0, event.Width, event.Height, POSSIZE)
            self._backdrop.setPosSize(0, 0, event.Width, event.Height, POSSIZE)
            if self.list is not None:
                self.list.set_bounds(event.Width, event.Height)

    def windowMoved(self, event):
        pass

    def windowShown(self, event):
        pass

    def windowHidden(self, event):
        if self.list is not None and not self._disposed:
            self.list.panel_hidden()

    def disposing(self, event):
        self.dispose()


class PanelFactory(unohelper.Base, XUIElementFactory, XServiceInfo):
    """Create a panel only when the sidebar requests one."""

    def __init__(self, context):
        self._context = context

    def createUIElement(self, resource_url, arguments):
        if resource_url != RESOURCE_URL:
            raise NoSuchElementException(resource_url, self)
        named = {argument.Name: argument.Value for argument in arguments}
        return SheetPanel(self._context, resource_url, named)

    def getImplementationName(self):
        return FACTORY

    def supportsService(self, name):
        return name in self.getSupportedServiceNames()

    def getSupportedServiceNames(self):
        return (FACTORY, "com.sun.star.ui.UIElementFactory")
