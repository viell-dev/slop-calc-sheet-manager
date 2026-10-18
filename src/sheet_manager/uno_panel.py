"""UNO sidebar adapter: the panel factory and the panel that holds the sheet list."""

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


class SheetPanel(
    unohelper.Base, XUIElement, XToolPanel, XSidebarPanel, XComponent, XWindowListener
):
    """A tab-control peer, sized by the sidebar's panel container, holding the sheet list."""

    def __init__(self, context, resource_url, arguments):
        self.ResourceURL = resource_url
        self.Type = TOOLPANEL
        self.Frame = arguments["Frame"]
        self._parent = arguments["ParentWindow"]
        self._listeners = []
        self._disposed = False
        bounds = self._parent.getPosSize()
        descriptor = WindowDescriptor()
        descriptor.Type = uno.Enum("com.sun.star.awt.WindowClass", "CONTAINER")
        # A plain "window" leaves clicks unhandled: VCL starts undocking the sidebar.
        descriptor.WindowServiceName = "tabcontrol"
        descriptor.ParentIndex = -1
        descriptor.Parent = self._parent
        descriptor.Bounds = Rectangle(0, 0, bounds.Width, bounds.Height)
        descriptor.WindowAttributes = SHOW
        self.Window = self._parent.getToolkit().createWindow(descriptor)
        # When a modifier key changes, VCL's mnemonic handling (gtk3, Windows) recurses into
        # the current page of every tab control in the window and crashes on a control
        # without pages. One hidden, empty page prevents that; a shown page would cover the
        # list. The tab control shows a page again only when switching pages.
        self.Window.insertTab()
        for page in self.Window.getWindows():
            page.setVisible(False)
        self.list = None
        try:
            self.list = SheetList(context, self.Frame, self.Window)
            self.list.set_bounds(bounds.Width, bounds.Height)
        except Exception:
            # An empty panel is better than a sidebar that fails to open.
            report("creating the sheet list")
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
        return 150

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
