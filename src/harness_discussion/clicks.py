"""Decides whether a mouse-up may have just selected text. Shared by the Windows and macOS triggers."""
DRAG_PX = 6


class Clicks:
    def __init__(self, multi_click_s):
        self.multi_click_s = multi_click_s
        self._down, self._last = (0, 0), (0, 0, float("-inf"))

    def down(self, x, y):
        self._down = (x, y)

    def up(self, x, y, now) -> bool:
        """True after a drag or a double or triple click."""
        lx, ly, lt = self._last
        self._last = (x, y, now)
        dragged = abs(x - self._down[0]) > DRAG_PX or abs(y - self._down[1]) > DRAG_PX
        multi = now - lt < self.multi_click_s and abs(x - lx) <= 4 and abs(y - ly) <= 4
        return dragged or multi
