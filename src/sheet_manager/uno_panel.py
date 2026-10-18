"""UNO sidebar adapter. No document content or selection is changed here."""

import weakref
from typing import cast

import uno
import unohelper
from com.sun.star.awt import Rectangle, WindowDescriptor, XWindowListener
from com.sun.star.container import NoSuchElementException, XNameAccess
from com.sun.star.lang import EventObject, XComponent, XServiceInfo
from com.sun.star.ui import LayoutSize, XSidebarPanel, XToolPanel, XUIElement, XUIElementFactory

FACTORY = "dev.viell.sheetmanager.PanelFactory"
RESOURCE_URL = "private:resource/toolpanel/SheetManager/Panel"
TOOLPANEL = cast(int, uno.getConstantByName("com.sun.star.ui.UIElementType.TOOLPANEL"))
SHOW = cast(int, uno.getConstantByName("com.sun.star.awt.WindowAttribute.SHOW"))
POSSIZE = cast(int, uno.getConstantByName("com.sun.star.awt.PosSize.POSSIZE"))
_panels = weakref.WeakSet()


class EmptyPanel(
    unohelper.Base, XUIElement, XToolPanel, XSidebarPanel, XComponent, XWindowListener
):
    """One empty tab-control peer, sized by the sidebar's panel container."""

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
        self._parent.addWindowListener(self)
        _panels.add(self)

    def getRealInterface(self):
        return self

    def createAccessible(self, parent_accessible):
        return self.Window

    def getHeightForWidth(self, width):
        return LayoutSize(0, -1, 400)

    def getMinimalWidth(self):
        return 150

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        _panels.discard(self)
        self._parent.removeWindowListener(self)
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

    def windowMoved(self, event):
        pass

    def windowShown(self, event):
        pass

    def windowHidden(self, event):
        pass

    def disposing(self, event):
        self.dispose()


class PanelFactory(unohelper.Base, XUIElementFactory, XServiceInfo, XNameAccess):
    """Lazy factory with read-only access to live panels for activation diagnostics.

    The weak registry neither retains closed frames nor creates panels on request. It
    exposes only existing UNO interfaces, with no test commands or document mutations.
    """

    def __init__(self, context):
        self._context = context

    def createUIElement(self, resource_url, arguments):
        if resource_url != RESOURCE_URL:
            raise NoSuchElementException(resource_url, self)
        named = {argument.Name: argument.Value for argument in arguments}
        return EmptyPanel(self._context, resource_url, named)

    def getImplementationName(self):
        return FACTORY

    def supportsService(self, name):
        return name in self.getSupportedServiceNames()

    def getSupportedServiceNames(self):
        return (FACTORY, "com.sun.star.ui.UIElementFactory")

    def getElementType(self):
        return uno.getTypeByName("com.sun.star.ui.XUIElement")

    def hasElements(self):
        return bool(_panels)

    def getElementNames(self):
        return tuple(panel.ResourceURL + "/" + str(id(panel)) for panel in _panels)

    def hasByName(self, name):
        return name in self.getElementNames()

    def getByName(self, name):
        for panel in _panels:
            if name == panel.ResourceURL + "/" + str(id(panel)):
                return panel
        raise NoSuchElementException(name, self)
