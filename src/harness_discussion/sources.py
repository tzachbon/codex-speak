"""App's voice-source state: the cached statuses and the floating bar's source button."""
import logging
import threading

log = logging.getLogger("harness_discussion")


class Sources:
    """Mixed into core.App, which owns chain, cfg, popup, events and change()."""

    def refresh_statuses(self):
        """Settings shows the cached result: status() can take seconds, as macOS asks a login shell for codex."""
        if not self._checking.acquire(blocking=False):
            return  # the running check reports soon enough
        def work():
            statuses = {}
            try:
                for e in self.chain.engines:
                    try:
                        statuses[e.name] = e.status() if hasattr(e, "status") else "ready"
                    except Exception as err:
                        log.warning("%s status failed: %s", e.name, type(err).__name__)
                        statuses[e.name] = "missing"
                self.statuses = self.chain.statuses = statuses
            finally:
                self._checking.release()
            self.events.put(("statuses",))
        threading.Thread(target=work, daemon=True).start()

    def _show_source(self):
        """Idle bar label: the source the next read starts with. While reading, engine events set it."""
        if not self.chain.busy:
            self.popup.set_source(self.chain.order()[0].name)

    def _source_choices(self):
        """The bar's menu: enabled sources not known to be unready, in the saved order, else what a read would use."""
        ready = [name for name, on in self.cfg["sources"] if on and self.statuses.get(name, "ready") == "ready"]
        return ready or [e.name for e in self.chain.order()]

    def _popup_source(self, name):
        sources = self.cfg["sources"]
        self.change("sources", [s for s in sources if s[0] == name] + [s for s in sources if s[0] != name])
