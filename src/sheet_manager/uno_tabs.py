"""Following Calc's tab selection and the sidebar's visibility, for one sheet list.

Calc sends no reliable notification for a tab selection that keeps the same active sheet, so the
observer caches the reflected `getSelectedSheets` method and samples its retained controller on
the UI thread every `VIEW_INTERVAL`. Never run that getter in a timer worker or a toolkit
listener: it does not take the solar mutex itself, and VCL runs toolkit mouse listeners without
it (#269). Compare logical name membership, establish a fresh baseline after a namespace or
proof change, and never consume pending modify evidence through the structure monitor's
`check()` merely to observe tabs (#66). List input acknowledges the preceding native state at
the listener boundary (`note_input`), so that queued Enter, menu, type-ahead, and move requests
cannot have an older sample replace their picks.
Observation is skipped while the list says it is paused (a held tree press, a drag, the menu, a
move, or a restoration), during a document lock, and during Calc's view of an own move's replay
(#91). A token rejects a cancelled timer already posted to the UI queue, so that timer chains
cannot duplicate. The same sample applies the list's palette (#141), behind the same barriers, so
that no colour listener or timer is added.

Sidebar visibility. A hidden panel checks its visibility every `HIDDEN_VIEW_INTERVAL` without
reading native tabs. Test the sidebar's visibility before calling `deck.isActive()`, which
dereferences its native controller, then the deck's activity and the panel's expansion; native
child-window visibility misses GTK hiding. Cached wrappers are dropped after the sidebar closes,
and observation stops on disposal or controller replacement. A panel wrapper is kept while the
panel is collapsed or inactive, because fresh `XPanel` discovery runs native deck layout: check
deck activity before a fresh discovery, and treat `NoSuchElementException` as a context that is
temporarily unavailable. Actual native panel disposal disposes the list too.

Contract. One observer belongs to one `uno_list.SheetList`, its host, and runs only on
LibreOffice's main thread; `note_input` is the one method a toolkit listener calls, and it only
posts. `refreshed` samples, so the host refreshes only in main-thread work, never inside a
listener; a drag on stale rows posts its refresh (#264), and a double click posts its
activation, which reads the tabs too (#269). The observer owns its timer chain, the
cached sidebar wrappers, and the baseline: the last sampled active sheet and tabs, with the
names, the structure generation, and the host's input count they were sampled at. A sample
follows Calc only when the state changed from that baseline, under the same names and
generation, with no newer host input, no pending acknowledgement, and no native picks still
awaiting the host's queued intake. `stop` ends observation for good once the view is gone,
although a tick already scheduled still samples once; `dispose` also rejects queued ticks and
acknowledgements, and the host disposes the observer before releasing its own listeners and
controls. The host owns the picks and decides how to follow (`TabHost`).
"""

from typing import Any, Protocol

from com.sun.star.container import NoSuchElementException
from com.sun.star.lang import DisposedException

from sheet_manager.uno_calc import Later, MainThread

VIEW_INTERVAL = 0.25
HIDDEN_VIEW_INTERVAL = 1.0


class TabHost(Protocol):
    """What the observer needs from its sheet list."""

    @property
    def input_count(self) -> int:
        """The list's own input count, which a newer gesture or key raises."""
        ...

    @property
    def proven(self) -> int:
        """The structure generation the list's rows and picks were proved at."""
        ...

    def names(self) -> list[str]:
        """The sheet names the list shows, in order."""
        ...

    def observation_paused(self) -> bool:
        """Whether the list's own input or change is in progress, so Calc's tabs are transient."""
        ...

    def sheets_changed(self) -> None:
        """The shown rows are behind Calc's sheets: refresh them, unless one is pending."""
        ...

    def pending_native_picks(self) -> bool:
        """Whether native picks await the list's queued intake; it takes them later, if so."""
        ...

    def follow_tabs(self, tabs: list[str], active: str) -> None:
        """Pick Calc's newly selected tabs, as Calc's rather than the user's picks."""
        ...

    def show_tabs(self, tabs: tuple[str, ...]) -> None:
        """Show which tabs Calc groups, in the list's status line."""
        ...

    def apply_palette(self) -> None:
        """Follow Calc's document colours (`uno_theme`)."""
        ...


class TabObserver:
    def __init__(
        self,
        main: MainThread,
        frame: Any,
        controller: Any,
        document: Any,
        monitor: Any,
        tabs_method: Any,
        host: TabHost,
        generation: int,
    ) -> None:
        """`tabs_method` is the reflected `getSelectedSheets` (`uno_calc.selected_tabs_method`);
        `generation` is the structure generation the host's first rows will be proved at."""
        self._main = main
        self._frame = frame
        self._controller = controller
        self._document = document
        self._monitor = monitor
        self._tabs_method = tabs_method
        self._host = host
        self._disposed = False
        self._stopped = False
        self._timer: Later | None = None
        self._token: object | None = None
        self._controls: tuple[Any, Any] | None = None  # The deck and panel, while kept.
        self._state: tuple[str, frozenset[str]] | None = None  # Active sheet and tabs.
        self._names: frozenset[str] = frozenset()
        self._generation = generation
        self._input = 0
        self._ack_pending = False

    @property
    def stopped(self) -> bool:
        return self._stopped

    def stop(self) -> None:
        """The view is gone, for example while a menu command ran: schedule no further sample.

        A tick already scheduled still runs once, and can follow Calc's tabs if the view is in
        fact still shown; acknowledgements and refreshes no longer sample. `dispose` also
        rejects that tick.
        """
        self._stopped = True

    def start(self) -> None:
        self._schedule(VIEW_INTERVAL)

    def dispose(self) -> None:
        self._disposed = True
        self._token = None
        if self._timer is not None:
            self._timer.cancel()
        self._controls = None

    def visible(self) -> bool:
        """Whether the list's deck is shown and its panel expanded in this frame's sidebar."""
        if self._frame.getController() != self._controller:
            self._stopped = True  # Reload replaced this controller; its panel owns disposal.
            self._controls = None
            return False
        if self._frame.getContainerWindow().IsMinimized:
            return False
        sidebar = self._controller.getSidebar()
        if not sidebar.isVisible():
            self._controls = None
            return False
        if self._controls is None:
            try:
                deck = sidebar.getDecks().getByName("SheetManagerDeck")
                if not deck.isActive():
                    return False
                panel = deck.getPanels().getByName("SheetManagerPanel")
            except NoSuchElementException:
                return False  # A reopened sidebar's native context may not be ready yet.
            self._controls = deck, panel
        deck, panel = self._controls
        # isActive dereferences the native sidebar controller: the visibility guard above
        # must precede it. Parent-window visibility alone misses GTK container hiding.
        # A fresh XPanel lookup lays out the native deck. Retain it while collapsed or
        # inactive; actual panel disposal synchronously disposes the list and this cache.
        return bool(deck.isActive() and panel.isExpanded())

    def _schedule(self, seconds: float) -> None:
        if self._disposed or self._stopped or self._timer is not None:
            return
        token = object()
        self._token = token
        self._timer = self._main.later(
            seconds, lambda: self._tick(token), "observing Calc's selected tabs"
        )

    def _tick(self, token: object) -> None:
        if self._disposed or token is not self._token:
            return  # A cancelled callback may already be in the native queue.
        self._timer, self._token = None, None
        visible = False
        try:
            visible = self.visible()
            if visible:
                self.observe(False)
        except DisposedException:
            self._stopped = True
        except Exception:
            self._stopped = True  # Report once rather than start a repeating error loop.
            raise
        finally:
            self._schedule(VIEW_INTERVAL if visible else HIDDEN_VIEW_INTERVAL)

    def note_input(self) -> None:
        """Acknowledge preceding Calc state after this input, coalescing forwarded callbacks.

        Called from toolkit listeners, so it only posts: never invoke the native selected-tabs
        getter there. The host's raised input count also protects a sample that runs before
        this acknowledgement reaches the UI queue.
        """
        if self._ack_pending:
            return
        self._ack_pending = True
        self._main.post(self.acknowledge, "noting the list's newer input")

    def acknowledge(self) -> None:
        """Take Calc's current tabs as the baseline, without following them."""
        self._ack_pending = False
        if not self._disposed and not self._stopped:
            try:
                if self.visible():
                    self.observe(True)
            except DisposedException:
                self._stopped = True
            except Exception:
                self._stopped = True
                raise

    def remember(self, active: str, tabs: tuple[str, ...]) -> None:
        """Make this state the baseline, at the host's current rows, proof and input."""
        self._state = active, frozenset(tabs)
        self._names = frozenset(self._host.names())
        self._generation = self._host.proven
        self._input = self._host.input_count
        self._host.show_tabs(tabs)

    def refreshed(self, generation: int) -> None:
        """The host refreshed at `generation`: a new namespace or proof needs a new baseline.

        Replacement or rename is not a request to pick the new sheet under an old name. The
        baseline is established before the refreshed rows become usable, so that a tab change
        after the refresh returns is not mistaken for it.
        """
        if self._generation != generation or self._names != frozenset(self._host.names()):
            self._state = None
            self._input = self._host.input_count
            if not self._stopped:
                self.observe(True)

    def observe(self, acknowledge: bool) -> None:
        """Sample Calc's tabs; follow a change unless `acknowledge` or newer list input."""
        if self._host.observation_paused():
            return
        if self._document.hasControllersLocked() or self._document.isActionLocked():
            return
        if self._monitor.events.viewing_replay() is not None:
            return  # Calc's view during an own move's replay, until it is restored (#91).
        self._host.apply_palette()
        generation = self._monitor.generation  # Never consume pending modify evidence (#66).
        if generation != self._host.proven:
            self._state = None
            self._host.sheets_changed()
            return
        names = tuple(self._document.getSheets().getElementNames())
        if names != tuple(self._host.names()):
            self._host.sheets_changed()
            return
        active = str(self._controller.getActiveSheet().getName())
        indices = self._tabs_method.invoke(self._controller, ())[0]
        if any(index < 0 or index >= len(names) for index in indices):
            return
        tabs = tuple(names[index] for index in sorted(indices))
        if self._monitor.generation != generation:
            return
        if self._generation != generation or self._names != frozenset(names):
            self._state = None  # A new namespace/proof establishes a baseline, not new picks.
        state = active, frozenset(tabs)
        changed = self._state is not None and state != self._state
        newer_input = self._host.input_count != self._input or self._ack_pending
        # Native input can precede its queued mouse listener. Do not follow Calc over it, or
        # adopt the native toggle before the owned listener has handled that same input.
        pending_picks = self._host.pending_native_picks()
        self.remember(active, tabs)
        if changed and not acknowledge and not newer_input and not pending_picks:
            self._host.follow_tabs(list(tabs), active)
