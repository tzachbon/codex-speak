"""Caption rendering checks need no speech service or audio device."""
import unittest
import tkinter as tk
import ctypes
import gc

from select_to_tts.captions import caption_layout, GdiLine, compose_caption, CaptionSurface
from select_to_tts.popup import Popup


class CaptionLayout(unittest.TestCase):
    def test_top_edge_on_negative_coordinate_monitor_keeps_strip_above_controls(self):
        bar, caption = caption_layout((-1800, -200, 220, 32), (-1920, -200, 0, 880), 340, 22, 12)
        self.assertEqual(bar, (-1800, -166, 220, 32))
        self.assertEqual(caption, (-1860, -200, 340, 22))

    def test_narrow_work_area_clamps_both_windows(self):
        bar, caption = caption_layout((250, 400, 220, 32), (100, 50, 260, 450), 340, 22, 12)
        self.assertEqual(bar, (100, 400, 160, 32))
        self.assertEqual(caption, (100, 366, 160, 22))


class CaptionPixels(unittest.TestCase):
    def test_repeated_native_raster_creation_releases_gdi_objects(self):
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        process = kernel.GetCurrentProcess()
        resources = ctypes.windll.user32.GetGuiResources
        resources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        resources.restype = ctypes.c_uint
        with GdiLine("Warm font cache", "Segoe UI", 14, 180, 26):
            pass
        before = resources(process, 0)
        for _ in range(30):
            with GdiLine("Unicode שלום العربية", "Segoe UI", 14, 180, 26) as line:
                self.assertGreater(line.mask(0).getextrema()[1], 0)
        self.assertEqual(resources(process, 0), before)

    def test_native_unicode_text_has_faded_edges_and_independent_background_alpha(self):
        with GdiLine("Sentence שלום العربية with mixed direction", "Segoe UI", 14, 180, 26) as line:
            self.assertGreater(line.text_width, 180)
            mask = line.mask(0)
            transparent = compose_caption(mask, False, 0)
            background = compose_caption(mask, True, 0.6)
            self.assertGreater(transparent.getchannel("A").getextrema()[1], 200)
            self.assertEqual(transparent.getchannel("A").crop((0, 0, 1, 26)).getextrema(), (0, 0))
            self.assertEqual(transparent.getchannel("A").crop((179, 0, 180, 26)).getextrema(), (0, 0))
            self.assertEqual(background.getpixel((90, 1))[3], 153)
            ink = max(((x, y) for y in range(26) for x in range(30, 150)), key=lambda p: mask.getpixel(p))
            self.assertEqual(transparent.getpixel(ink)[3], background.getpixel(ink)[3])


class CaptionWindow(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.bar = tk.Toplevel(self.root)
        self.bar.overrideredirect(True)
        self.bar.geometry("220x32+120+120")
        self.root.update_idletasks()
        self.caption = CaptionSurface(self.bar, "Segoe UI", lambda: ((120, 120, 220, 32), (0, 0, 1920, 1080)))

    def tearDown(self):
        self.caption.close()
        self.root.destroy()
        self.caption = self.bar = self.root = None
        gc.collect()  # Tk cycles must release their interpreter on its owning thread.

    def pump(self, duration):
        self.root.after(duration, self.root.quit)
        self.root.mainloop()

    def test_long_sentence_pause_freezes_then_resume_moves_and_hide_cancels(self):
        self.caption.show_text("A long sentence with enough words to overflow the small caption line. " * 4)
        self.pump(100)
        self.assertTrue(self.caption.text, "native window update failed")
        self.assertGreater(self.caption.offset, 0)
        self.caption.set_paused(True)
        held = self.caption.offset
        self.pump(100)
        self.assertEqual(self.caption.offset, held)
        self.caption.configure(12, True, 0.5)
        self.assertEqual(self.caption.offset, held)
        self.caption.set_paused(False)
        self.pump(100)
        self.assertGreater(self.caption.offset, held)
        self.caption.hide()
        self.pump(80)
        self.assertEqual(self.caption.text, "")
        self.assertEqual(self.caption.offset, 0)
        self.assertFalse(self.caption.win.winfo_viewable())

    def test_new_rtl_sentence_starts_at_its_right_edge(self):
        self.caption.show_text("English sentence")
        self.caption.show_text("משפט ארוך עם הרבה מילים לקריאה. " * 8)
        start = self.caption.offset
        self.assertGreater(start, 0)
        self.pump(100)
        self.assertTrue(self.caption.text, "native window update failed")
        self.assertLess(self.caption.offset, start)

    def test_native_caption_is_clickthrough_nonactivating_and_cleans_up_on_parent_destroy(self):
        from select_to_tts.captions import _get_style
        ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
        foreground = ctypes.windll.user32.GetForegroundWindow()
        self.caption.show_text("A harmless caption sample")
        self.pump(60)
        style = _get_style(self.caption.hwnd, -20)
        self.assertEqual(style & (0x08000000 | 0x80000 | 0x20), 0x08000000 | 0x80000 | 0x20)
        self.assertEqual(ctypes.windll.user32.GetForegroundWindow(), foreground)
        self.bar.destroy()
        self.assertIsNone(self.caption._line)


class PopupCaptionLifecycle(unittest.TestCase):
    def test_popup_stop_and_hide_clear_caption_and_containment_excludes_strip(self):
        root = tk.Tk()
        root.withdraw()
        callback = lambda *args: None
        popup = Popup(root, 1, on_play=callback, on_stop=callback, on_pause=callback,
                      on_resume=callback, on_lang=callback, on_speed=callback)
        try:
            popup.show("Selected text", 140, 140)
            popup.set_playing(True)
            popup.set_caption("Current sentence")
            root.update()
            self.assertTrue(popup.caption.text)
            x, y, width, height = popup.caption.bounds
            self.assertFalse(popup.contains(x + width // 2, y + height // 2))
            popup.set_playing(False)
            self.assertEqual(popup.caption.text, "")
            popup.set_playing(True)
            popup.set_caption("Next current sentence")
            popup.hide()
            self.assertEqual(popup.caption.text, "")
        finally:
            root.destroy()
            popup = root = None
            gc.collect()


if __name__ == "__main__":
    unittest.main()
