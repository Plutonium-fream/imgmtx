"""Exercise PNG-key selection and live themes through the desktop workflows."""

import ctypes
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from imgmtx.app import App, ImageViewer


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except (AttributeError, OSError):
    pass


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix=".imgmtx-feature-test-", dir=Path(__file__).resolve().parent
        )
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.original = self.folder / "original.png"
        self.hidden = self.folder / "hidden.png"
        self.wrong = self.folder / "wrong.png"
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("feature-test", "Keep every file byte unchanged.")
        Image.new("RGBA", (21, 9), (90, 30, 150, 101)).save(self.original, pnginfo=metadata)
        Image.new("RGBA", (7, 19), (10, 180, 80, 56)).save(self.hidden, pnginfo=metadata)
        Image.new("RGB", (3, 2), "red").save(self.wrong)
        self.original_bytes = self.original.read_bytes()
        self.hidden_bytes = self.hidden.read_bytes()
        self.errors = []
        self.app = App()
        self.app.withdraw()
        self.app.report_callback_exception = lambda kind, value, trace: self.errors.append(value)
        self.addCleanup(self.close_app)
        self.settle()

    def dispose(self, app):
        for pending in app.tk.call("after", "info"):
            app.tk.call("after", "cancel", pending)
        app.destroy()

    def close_app(self):
        self.dispose(self.app)

    def settle(self):
        self.app.update()
        self.assertEqual(self.errors, [], "A desktop callback failed")

    def wait_for_job(self):
        deadline = time.monotonic() + 10
        while self.app.busy and time.monotonic() < deadline:
            self.settle()
            time.sleep(0.005)
        self.settle()
        self.assertFalse(self.app.busy, "Desktop operation did not complete")

    def choose_original(self, path=None):
        with patch("imgmtx.app.filedialog.askopenfilename", return_value=str(path or self.original)):
            self.app.choose_original()
            self.wait_for_job()

    def choose_second(self, path):
        with patch("imgmtx.app.filedialog.askopenfilename", return_value=str(path)):
            self.app.choose_second()
            self.wait_for_job()

    def load_pair(self):
        self.choose_original()
        self.choose_second(self.hidden)

    def create_key(self, name="secret.imgkey"):
        path = self.folder / name
        with patch("imgmtx.app.filedialog.asksaveasfilename", return_value=str(path)) as dialog:
            self.app.action.invoke()
            self.wait_for_job()
        self.assertTrue(path.exists(), self.app.status.cget("text"))
        return path, dialog.call_args.kwargs

    def reveal(self, key):
        self.app.switch("reveal")
        self.choose_second(key)
        self.app.action.invoke()
        self.wait_for_job()
        self.assertIsNotNone(self.app.result, self.app.status.cget("text"))
        self.assertEqual(self.app.result.data, self.hidden_bytes)

    def assert_sources_unchanged(self):
        self.assertEqual(self.original.read_bytes(), self.original_bytes)
        self.assertEqual(self.hidden.read_bytes(), self.hidden_bytes)

    def test_image_choice_creates_viewable_png_key_then_recovers_and_exports_exact_image(self):
        self.load_pair()
        self.app.format_png.invoke()
        self.assertEqual(self.app.key_format.get(), "png")
        self.app.theme_toggle.invoke()
        key, dialog = self.create_key("secret.key.png")
        self.assertEqual(dialog["defaultextension"], ".png")
        self.assertTrue(dialog["initialfile"].endswith(".key.png"))
        with Image.open(key) as carrier:
            self.assertEqual(carrier.format, "PNG")
            self.assertEqual(carrier.mode, "RGB")
            carrier.load()
        key_bytes = key.read_bytes()
        self.app.clear()
        self.choose_original()
        self.reveal(key)
        self.assertEqual(self.app.theme_name, "dark")
        output = self.folder / "recovered.png"
        with patch("imgmtx.app.filedialog.asksaveasfilename", return_value=str(output)):
            self.app.save.invoke()
            self.wait_for_job()
        self.assertEqual(output.read_bytes(), self.hidden_bytes)
        self.assertEqual(key.read_bytes(), key_bytes)
        self.assert_sources_unchanged()

    def test_theme_switches_preserve_loaded_create_inputs_and_format_choice(self):
        self.load_pair()
        self.app.format_png.invoke()
        original, hidden = self.app.original, self.app.hidden
        original_pixels = self.app.left.display_image.tobytes()
        hidden_pixels = self.app.right.display_image.tobytes()
        light_bg = self.app.cget("bg")
        light_action = self.app.action.cget("bg")
        for expected in ("dark", "light"):
            with self.subTest(theme=expected):
                self.app.theme_toggle.invoke()
                self.settle()
                self.assertEqual(self.app.theme_name, expected)
                self.assertEqual(self.app.cget("bg"), self.app.palette["bg"])
                self.assertEqual(self.app.left.canvas.cget("bg"), self.app.palette["well"])
                self.assertEqual(self.app.theme_toggle.cget("text"), "Light mode" if expected == "dark" else "Dark mode")
                self.assertIs(self.app.original, original)
                self.assertIs(self.app.hidden, hidden)
                self.assertEqual(self.app.left.display_image.tobytes(), original_pixels)
                self.assertEqual(self.app.right.display_image.tobytes(), hidden_pixels)
                self.assertEqual(self.app.key_format.get(), "png")
                self.assertEqual(str(self.app.action.cget("state")), "normal")
                if expected == "dark":
                    self.assertNotEqual(self.app.cget("bg"), light_bg)
                    self.assertNotEqual(self.app.action.cget("bg"), light_action)
        self.assertEqual(self.app.cget("bg"), light_bg)
        self.assert_sources_unchanged()

    def test_revealed_result_and_open_viewer_and_help_survive_theme_switches(self):
        self.load_pair()
        key, _ = self.create_key()
        self.reveal(key)
        self.app.deiconify()
        self.app.right.enlarge.invoke()
        self.app.help()
        self.settle()
        viewer = next(child for child in self.app.winfo_children() if isinstance(child, ImageViewer))
        help_window = next(child for child in self.app.winfo_children()
                           if isinstance(child, tk.Toplevel) and child.title() == "How ImgMtx works")
        viewer_pixels = viewer.source.tobytes()
        result, key_data = self.app.result, self.app.key_data
        for expected in ("dark", "light"):
            with self.subTest(theme=expected):
                self.app.theme_toggle.invoke()
                self.settle()
                self.assertIs(self.app.result, result)
                self.assertIs(self.app.key_data, key_data)
                self.assertEqual(self.app.right.info.data, self.hidden_bytes)
                self.assertEqual(str(self.app.save.cget("state")), "normal")
                self.assertEqual(viewer.cget("bg"), self.app.palette["bg"])
                self.assertEqual(viewer.canvas.cget("bg"), self.app.palette["well"])
                self.assertEqual(help_window.cget("bg"), self.app.palette["card"])
                self.assertEqual(viewer.source.tobytes(), viewer_pixels)
        self.assert_sources_unchanged()

    def test_mismatch_error_stays_visible_in_both_themes_without_enabling_save(self):
        self.load_pair()
        key, _ = self.create_key()
        self.reveal(key)
        self.choose_original(self.wrong)
        self.app.action.invoke()
        self.wait_for_job()
        message = self.app.status.cget("text")
        self.assertIn("does not match this key", message)
        for expected in ("dark", "light"):
            with self.subTest(theme=expected):
                self.app.theme_toggle.invoke()
                self.settle()
                self.assertEqual(self.app.status.cget("text"), message)
                self.assertEqual(self.app.status.cget("fg"), self.app.palette["error"])
                self.assertEqual(str(self.app.save.cget("state")), "disabled")
                self.assertEqual(str(self.app.action.cget("state")), "normal")
                self.assertIsNone(self.app.result)
                self.assertIsNone(self.app.right.info)

    def assert_unclipped(self, widget):
        self.assertTrue(widget.winfo_ismapped(), f"{widget} is hidden")
        self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth())
        self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        right, bottom = x + widget.winfo_width(), y + widget.winfo_height()
        ancestor = widget.master
        while ancestor is not None:
            self.assertGreaterEqual(x, ancestor.winfo_rootx(), f"{widget} clips on left")
            self.assertGreaterEqual(y, ancestor.winfo_rooty(), f"{widget} clips above")
            self.assertLessEqual(right, ancestor.winfo_rootx() + ancestor.winfo_width(), f"{widget} clips on right")
            self.assertLessEqual(bottom, ancestor.winfo_rooty() + ancestor.winfo_height(), f"{widget} clips below")
            ancestor = ancestor.master

    def well_bounds(self):
        return tuple((well.winfo_x(), well.winfo_y(), well.winfo_width(), well.winfo_height())
                     for well in (self.app.left.canvas, self.app.right.canvas))

    def test_new_controls_fit_default_and_minimum_window_sizes_in_both_themes(self):
        self.app.deiconify()
        self.settle()
        sizes = [(self.app.winfo_width(), self.app.winfo_height()), self.app.minsize()]
        for size in sizes:
            self.app.geometry(f"{size[0]}x{size[1]}")
            self.settle()
            for mode in ("create", "reveal"):
                self.app.switch(mode)
                self.settle()
                baseline = self.well_bounds()
                for expected in ("light", "dark"):
                    with self.subTest(size=size, mode=mode, theme=expected):
                        if self.app.theme_name != expected:
                            self.app.theme_toggle.invoke()
                        self.settle()
                        for control in (self.app.theme_toggle, self.app.action):
                            self.assert_unclipped(control)
                        if mode == "create":
                            self.assert_unclipped(self.app.format_custom)
                            self.assert_unclipped(self.app.format_png)
                        else:
                            self.assert_unclipped(self.app.key_button)
                        for well in (self.app.left.canvas, self.app.right.canvas):
                            self.assertTrue(well.winfo_ismapped())
                            self.assertGreater(well.winfo_height(), 0)
                        self.assertEqual(self.well_bounds(), baseline)

    def test_a_new_app_starts_light_after_another_app_was_dark(self):
        self.app.theme_toggle.invoke()
        self.settle()
        self.assertEqual(self.app.theme_name, "dark")
        self.dispose(self.app)
        self.app = App()
        self.app.withdraw()
        self.app.report_callback_exception = lambda kind, value, trace: self.errors.append(value)
        self.settle()
        self.assertEqual(self.app.theme_name, "light")
        self.assertEqual(self.app.cget("bg"), self.app.palette["bg"])
        self.assertEqual(self.app.theme_toggle.cget("text"), "Dark mode")


if __name__ == "__main__":
    unittest.main()
