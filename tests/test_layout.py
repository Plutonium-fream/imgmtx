"""Geometry and image-viewer checks for the usable desktop work surface."""

import ctypes
import io
import unittest

from PIL import Image

from imgmtx.app import App, ImageViewer
from imgmtx.core import ImageInfo


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except (AttributeError, OSError):
    pass


def sample_png(size=(19, 11)):
    output = io.BytesIO()
    Image.new("RGBA", size, (23, 80, 160, 150)).save(output, format="PNG")
    return ImageInfo(output.getvalue(), *size)


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.app = App()
        self.addCleanup(self.close_app)
        self.errors = []
        self.app.report_callback_exception = (
            lambda kind, value, traceback: self.errors.append((kind, value))
        )
        self.app.update()
        self.default_size = self.app.winfo_width(), self.app.winfo_height()
        self.minimum_size = self.app.minsize()

    def close_app(self):
        # Cancel timers at Tcl level; each owning widget remains responsible
        # for deleting its registered callback when that widget is destroyed.
        for pending in self.app.tk.call("after", "info"):
            self.app.tk.call("after", "cancel", pending)
        self.app.destroy()

    def settle(self):
        self.app.update()
        self.assertEqual(self.errors, [], "A Tk callback raised an exception")

    def resize(self, size):
        self.app.geometry(f"{size[0]}x{size[1]}")
        self.settle()

    def bounds(self, widget):
        return (
            widget.winfo_rootx() - self.app.winfo_rootx(),
            widget.winfo_rooty() - self.app.winfo_rooty(),
            widget.winfo_width(),
            widget.winfo_height(),
        )

    def assert_inside_window(self, widget, label):
        self.assertTrue(widget.winfo_ismapped(), f"{label} is not visible")
        x, y, width, height = self.bounds(widget)
        self.assertGreater(width, 0, f"{label} has no width")
        self.assertGreater(height, 0, f"{label} has no height")
        self.assertGreaterEqual(x, 0, f"{label} extends left of the window")
        self.assertGreaterEqual(y, 0, f"{label} extends above the window")
        self.assertLessEqual(x + width, self.app.winfo_width(), f"{label} extends right of the window")
        self.assertLessEqual(y + height, self.app.winfo_height(), f"{label} extends below the window")
        ancestor = widget.master
        while ancestor is not None and ancestor is not self.app:
            ax, ay, aw, ah = self.bounds(ancestor)
            self.assertGreaterEqual(x, ax, f"{label} is clipped by its parent on the left")
            self.assertGreaterEqual(y, ay, f"{label} is clipped by its parent above")
            self.assertLessEqual(x + width, ax + aw, f"{label} is clipped by its parent on the right")
            self.assertLessEqual(y + height, ay + ah, f"{label} is clipped by its parent below")
            ancestor = ancestor.master

    def visible_controls(self):
        controls = [
            (self.app.reset, "Clear workspace"),
            (self.app.create_tab, "Create tab"),
            (self.app.reveal_tab, "Reveal tab"),
            (self.app.left.choose, "Original PNG chooser"),
            (self.app.left.enlarge, "Original Enlarge"),
            (self.app.right.enlarge, "Hidden Enlarge"),
            (self.app.action, "Primary action"),
        ]
        if self.app.mode == "create":
            controls.append((self.app.right.choose, "Hidden PNG chooser"))
        else:
            controls.extend([
                (self.app.key_button, "Key file chooser"),
                (self.app.save, "Save PNG"),
            ])
        return controls

    def assert_controls_unclipped(self):
        for control, name in self.visible_controls():
            self.assert_inside_window(control, name)
            self.assertGreaterEqual(
                control.winfo_width(), control.winfo_reqwidth(),
                f"{name} is narrower than its text and padding",
            )
            self.assertGreaterEqual(
                control.winfo_height(), control.winfo_reqheight(),
                f"{name} is shorter than its text and padding",
            )
        self.assert_inside_window(self.app.left.canvas, "Original image well")
        self.assert_inside_window(self.app.right.canvas, "Hidden image well")

    def assert_matching_wells(self):
        left = self.bounds(self.app.left.canvas)
        right = self.bounds(self.app.right.canvas)
        for index, name in ((1, "vertical position"), (2, "width"), (3, "height")):
            self.assertLessEqual(abs(left[index] - right[index]), 1, f"Image wells differ in {name}")
        self.assertLess(left[0] + left[2], right[0], "Image wells overlap")

    def test_controls_visible_and_unclipped_at_default_and_minimum_sizes(self):
        for size in (self.default_size, self.minimum_size):
            self.resize(size)
            for mode in ("create", "reveal"):
                with self.subTest(size=size, mode=mode):
                    self.app.switch(mode)
                    self.settle()
                    self.assert_controls_unclipped()
                    self.assertEqual(bool(self.app.right.choose.winfo_ismapped()), mode == "create")
                    self.assertEqual(bool(self.app.key_button.winfo_ismapped()), mode == "reveal")
                    self.assertEqual(bool(self.app.save.winfo_ismapped()), mode == "reveal")
                    if mode == "reveal":
                        self.assert_inside_window(self.app.key_name, "Selected key filename")

    def test_image_wells_keep_equal_size_and_position_across_modes(self):
        for size in (self.default_size, self.minimum_size):
            self.resize(size)
            baseline = None
            for mode in ("create", "reveal", "create"):
                with self.subTest(size=size, mode=mode):
                    self.app.switch(mode)
                    self.settle()
                    self.assert_matching_wells()
                    current = tuple(self.bounds(well) for well in (self.app.left.canvas, self.app.right.canvas))
                    if baseline is None:
                        baseline = current
                    else:
                        for before, after in zip(baseline, current):
                            for first, second in zip(before, after):
                                self.assertLessEqual(abs(first - second), 1, "Switching modes moved or resized an image well")

    def test_long_filenames_cannot_push_controls_out_of_the_window(self):
        self.resize(self.minimum_size)
        info = sample_png()
        self.app.left.set_image(info, "original_" + "long_filename_" * 100 + ".png")
        self.app.right.set_image(info, "hidden_" + "long_filename_" * 100 + ".png")
        self.settle()
        for mode in ("create", "reveal"):
            with self.subTest(mode=mode):
                self.app.switch(mode)
                if mode == "reveal":
                    self.app.key_name.config(text="secret_" + "long_filename_" * 100 + ".imgkey")
                self.settle()
                self.assertEqual((self.app.winfo_width(), self.app.winfo_height()), self.minimum_size)
                self.assert_controls_unclipped()
                self.assert_matching_wells()

    def test_enlarge_requires_an_image_and_opens_an_actual_viewer(self):
        info = sample_png()
        for preview in (self.app.left, self.app.right):
            with self.subTest(preview=preview.marker):
                self.assertEqual(str(preview.enlarge.cget("state")), "disabled")
                preview.enlarge.invoke()
                self.assertFalse(any(isinstance(child, ImageViewer) for child in self.app.winfo_children()))
                preview.set_image(info, "preview.png")
                self.settle()
                self.assertEqual(str(preview.enlarge.cget("state")), "normal")
                preview.enlarge.invoke()
                self.settle()
                viewers = [child for child in self.app.winfo_children() if isinstance(child, ImageViewer)]
                self.assertEqual(len(viewers), 1)
                viewer = viewers[0]
                self.assertTrue(viewer.winfo_ismapped())
                self.assertEqual(viewer.source.size, (info.width, info.height))
                # Cancel only this viewer's scheduled work before closing it.
                if viewer.job:
                    viewer.after_cancel(viewer.job)
                    viewer.job = None
                viewer.destroy()
                preview.set_image(None, "")
                self.assertEqual(str(preview.enlarge.cget("state")), "disabled")


if __name__ == "__main__":
    unittest.main()
