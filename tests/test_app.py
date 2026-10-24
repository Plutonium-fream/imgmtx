"""Exercise complete desktop workflows without native file-dialog automation."""

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from imgmtx.app import App


class AppWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix=".imgmtx-ui-test-", dir=Path(__file__).resolve().parent
        )
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.original = self.folder / "original.png"
        self.hidden = self.folder / "hidden.png"
        self.wrong_original = self.folder / "wrong-original.png"
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("purpose", "UI tests must preserve these exact bytes.")
        Image.new("RGBA", (9, 13), (16, 32, 64, 120)).save(
            self.original, pnginfo=metadata
        )
        hidden = Image.new("P", (17, 5), 3)
        hidden.putpalette([value for i in range(256) for value in (i, 255 - i, i // 2)])
        hidden.save(self.hidden, transparency=3, pnginfo=metadata)
        Image.new("RGB", (2, 3), "red").save(self.wrong_original)
        self.original_bytes = self.original.read_bytes()
        self.hidden_bytes = self.hidden.read_bytes()
        self.app = App()
        self.app.withdraw()
        self.addCleanup(self.close_app)
        self.callback_errors = []
        self.app.report_callback_exception = (
            lambda kind, value, traceback: self.callback_errors.append((kind, value))
        )
        self.app.update()

    def close_app(self):
        # Each test owns a separate Tcl root. Cancel scheduled callbacks before
        # destroying it so they cannot leak into the next test's event loop.
        for pending in self.app.tk.call("after", "info"):
            self.app.after_cancel(pending)
        self.app.destroy()

    def wait_for_job(self):
        deadline = time.monotonic() + 10
        while self.app.busy and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.005)
        self.app.update()
        self.assertFalse(self.app.busy, "Image operation did not finish within 10 seconds")
        self.assertEqual(self.callback_errors, [], "Tk callback raised an exception")

    def choose_original(self, path=None):
        with patch("imgmtx.app.filedialog.askopenfilename", return_value=str(path or self.original)):
            self.app.choose_original()
            self.wait_for_job()

    def choose_second(self, path):
        with patch("imgmtx.app.filedialog.askopenfilename", return_value=str(path)):
            self.app.choose_second()
            self.wait_for_job()

    def load_create_inputs(self):
        self.choose_original()
        self.choose_second(self.hidden)
        self.assertEqual(str(self.app.action.cget("state")), "normal")

    def create_key(self, name="secret.imgkey"):
        destination = self.folder / name
        with patch("imgmtx.app.filedialog.asksaveasfilename", return_value=str(destination)):
            self.app.action.invoke()
            self.wait_for_job()
        self.assertTrue(destination.exists(), self.app.status.cget("text"))
        return destination

    def reveal_key(self, key):
        self.app.switch("reveal")
        self.choose_second(key)
        self.assertEqual(str(self.app.action.cget("state")), "normal")
        self.app.action.invoke()
        self.wait_for_job()
        self.assertEqual(str(self.app.save.cget("state")), "normal")
        self.assertIsNotNone(self.app.right.info)
        self.assertEqual(self.app.right.info.data, self.hidden_bytes)

    def save_revealed(self, path):
        with patch("imgmtx.app.filedialog.asksaveasfilename", return_value=str(path)):
            self.app.save.invoke()
            self.wait_for_job()

    def assert_inputs_unchanged(self):
        self.assertEqual(self.original.read_bytes(), self.original_bytes)
        self.assertEqual(self.hidden.read_bytes(), self.hidden_bytes)

    def test_binary_key_create_reveal_and_exact_png_export(self):
        self.load_create_inputs()
        key = self.create_key()
        self.reveal_key(key)
        output = self.folder / "recovered.png"
        self.save_revealed(output)
        self.assertEqual(output.read_bytes(), self.hidden_bytes)
        self.assert_inputs_unchanged()

    def test_text_key_create_reveal_and_exact_png_export(self):
        self.load_create_inputs()
        key = self.create_key("secret.txt")
        self.assertTrue(key.read_bytes().isascii())
        self.reveal_key(key)
        output = self.folder / "from-text.png"
        self.save_revealed(output)
        self.assertEqual(output.read_bytes(), self.hidden_bytes)
        self.assert_inputs_unchanged()

    def test_mismatched_original_clears_previous_result_and_disables_save(self):
        self.load_create_inputs()
        key = self.create_key()
        self.reveal_key(key)
        self.choose_original(self.wrong_original)
        self.assertEqual(str(self.app.save.cget("state")), "disabled")
        self.assertIsNone(self.app.right.info)
        self.app.action.invoke()
        self.wait_for_job()
        self.assertIn("does not match this key", self.app.status.cget("text"))
        self.assertEqual(str(self.app.save.cget("state")), "disabled")
        self.assertIsNone(self.app.right.info)
        self.assert_inputs_unchanged()

    def test_damaged_key_clears_previous_result_and_disables_save(self):
        self.load_create_inputs()
        key = self.create_key()
        self.reveal_key(key)
        damaged = self.folder / "damaged.imgkey"
        data = key.read_bytes()
        damaged.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        self.choose_second(damaged)
        self.assertEqual(str(self.app.save.cget("state")), "disabled")
        self.app.action.invoke()
        self.wait_for_job()
        self.assertIn("checksum", self.app.status.cget("text"))
        self.assertEqual(str(self.app.save.cget("state")), "disabled")
        self.assertIsNone(self.app.right.info)

    def test_key_creation_refuses_existing_file_and_input_file(self):
        self.load_create_inputs()
        existing = self.folder / "existing.imgkey"
        existing.write_bytes(b"Keep this existing file unchanged.")
        for destination, expected in (
            (existing, "already exists"), (self.original, "cannot be overwritten")
        ):
            with self.subTest(destination=destination.name):
                with patch("imgmtx.app.filedialog.asksaveasfilename", return_value=str(destination)):
                    self.app.action.invoke()
                    self.wait_for_job()
                self.assertIn(expected, self.app.status.cget("text"))
                self.assertEqual(str(self.app.action.cget("state")), "normal")
        self.assertEqual(existing.read_bytes(), b"Keep this existing file unchanged.")
        self.assert_inputs_unchanged()

    def test_png_export_refuses_existing_file_and_input_file(self):
        self.load_create_inputs()
        key = self.create_key()
        self.reveal_key(key)
        existing = self.folder / "existing.png"
        existing.write_bytes(b"Do not replace this file.")
        self.save_revealed(existing)
        self.assertIn("already exists", self.app.status.cget("text"))
        self.save_revealed(self.original)
        self.assertIn("cannot be overwritten", self.app.status.cget("text"))
        self.assertEqual(existing.read_bytes(), b"Do not replace this file.")
        self.assertEqual(str(self.app.save.cget("state")), "normal")
        self.assert_inputs_unchanged()

    def test_clear_workspace_removes_previews_and_disables_actions(self):
        self.load_create_inputs()
        key = self.create_key()
        self.reveal_key(key)
        self.app.reset.invoke()
        self.assertIsNone(self.app.left.info)
        self.assertIsNone(self.app.right.info)
        self.assertEqual(self.app.key_name.cget("text"), "No key file selected")
        self.assertEqual(str(self.app.action.cget("state")), "disabled")
        self.assertEqual(str(self.app.save.cget("state")), "disabled")
        self.app.switch("create")
        self.assertIsNone(self.app.right.info)
        self.assertEqual(str(self.app.action.cget("state")), "disabled")
        self.assert_inputs_unchanged()

    def test_cancelled_dialogs_leave_inputs_and_output_state_unchanged(self):
        self.load_create_inputs()
        before = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        with patch("imgmtx.app.filedialog.askopenfilename", return_value=""):
            self.app.choose_original()
            self.app.choose_second()
        self.assertEqual(self.app.left.info.data, self.original_bytes)
        self.assertEqual(self.app.right.info.data, self.hidden_bytes)
        with patch("imgmtx.app.filedialog.asksaveasfilename", return_value=""):
            self.app.action.invoke()
            self.wait_for_job()
        self.assertIn("cancelled", self.app.status.cget("text"))
        self.assertEqual(str(self.app.action.cget("state")), "normal")
        self.assertEqual({path.name: path.read_bytes() for path in self.folder.iterdir()}, before)
        key = self.create_key()
        self.reveal_key(key)
        before = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        with patch("imgmtx.app.filedialog.askopenfilename", return_value=""):
            self.app.choose_second()
        with patch("imgmtx.app.filedialog.asksaveasfilename", return_value=""):
            self.app.save.invoke()
        self.assertEqual(self.app.right.info.data, self.hidden_bytes)
        self.assertEqual(str(self.app.save.cget("state")), "normal")
        self.assertEqual({path.name: path.read_bytes() for path in self.folder.iterdir()}, before)
        self.assert_inputs_unchanged()


if __name__ == "__main__":
    unittest.main()
