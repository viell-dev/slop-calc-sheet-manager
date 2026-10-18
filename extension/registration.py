"""Passive Python component entry point; the loader adds sibling pythonpath/."""

import unohelper

from sheet_manager.uno_panel import FACTORY, PanelFactory

g_ImplementationHelper = unohelper.ImplementationHelper()
# types-unopy leaves this method's return type unspecified.
g_ImplementationHelper.addImplementation(  # pyright: ignore[reportUnknownMemberType]
    PanelFactory, FACTORY, (FACTORY, "com.sun.star.ui.UIElementFactory")
)
