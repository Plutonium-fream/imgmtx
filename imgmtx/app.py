"""Local desktop interface for ImgMtx."""

from __future__ import annotations

import io
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from PIL import Image, ImageDraw, ImageTk
from . import __version__

from .core import (
    ImageInfo,
    ImgMtxError,
    create_key,
    encode_png_key,
    encode_text_key,
    read_key,
    read_png,
    reveal_image,
    write_new_file,
)
from .theme import LIGHT, PALETTES, canvas, color as tone, frame, paint, palette, retheme

# Widgets retain semantic roles so every open window can change theme together.
BG, CARD, EDGE = "bg", "card", "edge"
TEXT, MUTED, ACCENT, INK = "text", "muted", "accent", "ink"
ERROR, WELL, WELL_TEXT = "error", "well", "well_text"
FONT = "Segoe UI"
DISPLAY = "Bahnschrift"
MONO = "Consolas"
SCALE = 1.0


def scaled(value):
    return round(value * SCALE)


def window_size(window, width, height):
    width = min(scaled(width), window.winfo_screenwidth() - scaled(50))
    height = min(scaled(height), window.winfo_screenheight() - scaled(85))
    window.geometry(f"{width}x{height}+{scaled(20)}+{scaled(20)}")


def label(parent, text, size=11, color=TEXT, bold=False, family=FONT, **kwargs):
    widget = tk.Label(
        parent, text=text,
        font=(family, size, "bold" if bold else "normal"), **kwargs,
    )
    return paint(widget, bg=getattr(parent, "_theme_roles", {}).get("bg", BG), fg=color)


def button(parent, text, command, primary=False, **kwargs):
    widget = tk.Button(
        parent, text=text, command=command,
        relief="flat", borderwidth=0,
        font=(FONT, 10, "bold" if primary else "normal"), cursor="hand2",
        padx=scaled(16), pady=scaled(6),
        highlightthickness=1,
        takefocus=True, **kwargs,
    )
    return paint(widget, bg=ACCENT if primary else CARD, fg=INK if primary else TEXT,
                 activebackground="accent_hover" if primary else "hover",
                 activeforeground=INK if primary else TEXT, disabledforeground="disabled",
                 highlightbackground=ACCENT if primary else EDGE, highlightcolor=TEXT)


def size_text(count):
    if count < 1024:
        return f"{count} B"
    if count < 1024 * 1024:
        return f"{count / 1024:.1f} KB"
    return f"{count / (1024 * 1024):.1f} MB"


class Preview(tk.Frame):
    def __init__(self, parent, number, title, subtitle, command):
        super().__init__(parent)
        paint(self, bg=BG)
        self.info = None
        self.photo = None
        self.display_image = None
        self.resize_job = None
        self.command = command
        self.marker = number
        self.empty_title = "Original PNG" if number == "A" else "Hidden PNG"
        self.empty_detail = "Choose a file below, or click here"
        self.can_choose = True
        top = frame(self, bg=BG)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        top.grid(row=0, column=0, sticky="ew", pady=(0, scaled(3)))
        label(top, number, 11, ACCENT, True, family=MONO).pack(side="left", padx=(0, scaled(9)))
        self.title = label(top, title, 13, bold=True)
        self.title.pack(side="left")
        self.subtitle = label(self, subtitle, 9, MUTED, anchor="w")
        self.subtitle.grid(row=1, column=0, sticky="ew", pady=(0, scaled(8)))
        self.canvas = canvas(self, bg=WELL, highlightthickness=0, height=scaled(290), width=1, cursor="hand2")
        self.canvas.grid(row=2, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<Button-1>", self._choose_empty)
        self.canvas.bind("<Double-Button-1>", self._open_viewer)
        self.name = label(self, "No file selected", 10, MUTED, anchor="w", width=1)
        self.name.grid(row=3, column=0, sticky="ew", pady=(scaled(8), scaled(3)))
        self.meta = label(self, "PNG  /  up to 64 MB", 9, MUTED, family=MONO, anchor="w", width=1)
        self.meta.grid(row=4, column=0, sticky="ew", pady=(0, scaled(8)))
        controls = frame(self, bg=BG)
        controls.grid(row=5, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)
        self.choose = button(controls, "Choose PNG…", command)
        self.choose.grid(row=0, column=0, sticky="w")
        self.enlarge = button(controls, "Enlarge", self._open_viewer)
        self.enlarge.grid(row=0, column=1, sticky="e")
        self.enlarge.config(state="disabled")
        paint(self.enlarge, bg=BG, highlightbackground=BG)

    def empty_state(self, title, detail, can_choose=True):
        self.empty_title, self.empty_detail, self.can_choose = title, detail, can_choose
        self.canvas.config(cursor="hand2" if can_choose else "")
        self.draw()

    def _choose_empty(self, _event=None):
        if not self.info and self.can_choose and str(self.choose.cget("state")) == "normal":
            self.command()

    def _resize(self, _event=None):
        if self.resize_job:
            self.after_cancel(self.resize_job)
        self.resize_job = self.after(60, self.draw)

    def set_image(self, info, name):
        self.info = info
        self.display_image = None
        if info:
            with Image.open(io.BytesIO(info.data)) as source:
                self.display_image = source.convert("RGBA")
            self.name.config(text=name)
            paint(self.name, fg=TEXT)
            self.meta.config(text=f"{info.width:,} × {info.height:,} px   ·   {size_text(len(info.data))}   ·   PNG")
            self.choose.config(text="Change PNG…")
        else:
            self.name.config(text="No file selected")
            paint(self.name, fg=MUTED)
            self.meta.config(text="PNG  /  up to 64 MB")
            self.choose.config(text="Choose PNG…")
        self.enlarge.config(state="normal" if info else "disabled")
        self.draw()

    def draw(self):
        self.resize_job = None
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 20)
        height = max(self.canvas.winfo_height(), 20)
        if self.display_image:
            image = self.display_image.copy()
            image.thumbnail((max(1, width - scaled(40)), max(1, height - scaled(40))), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(checkerboard(image, palette(self)), master=self)
            self.canvas.create_image(width / 2, height / 2, image=self.photo)
        else:
            self.photo = None
            cx, cy = width / 2, height / 2
            radius = scaled(9)
            self.canvas.create_line(cx - radius, cy - scaled(26), cx + radius, cy - scaled(26), fill=tone(self, "well_mark"), width=1)
            self.canvas.create_line(cx, cy - scaled(26) - radius, cx, cy - scaled(26) + radius, fill=tone(self, "well_mark"), width=1)
            self.canvas.create_text(cx, cy + scaled(10), text=self.empty_title, fill=tone(self, "well_title"), font=(DISPLAY, 14))
            self.canvas.create_text(cx, cy + scaled(36), text=self.empty_detail, fill=tone(self, WELL_TEXT), font=(FONT, 9), width=max(1, width - scaled(40)))
        # The corners frame the image area without overlaying image pixels.
        inset, tick = scaled(10), scaled(9)
        for x, direction_x in ((inset, 1), (width - inset, -1)):
            for y, direction_y in ((inset, 1), (height - inset, -1)):
                self.canvas.create_line(x, y + direction_y * tick, x, y, x + direction_x * tick, y, fill=tone(self, "registration"), width=1)

    def _open_viewer(self, _event=None):
        if self.info:
            ImageViewer(self.winfo_toplevel(), self.info, self.name.cget("text"))


def checkerboard(image, colors=LIGHT):
    """Composite a preview only; image bytes and transparency remain unchanged."""
    board = Image.new("RGBA", image.size, colors["checker_dark"])
    draw = ImageDraw.Draw(board)
    tile = 14
    for y in range(0, image.height, tile):
        for x in range(0, image.width, tile):
            if (x // tile + y // tile) % 2 == 0:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=colors["checker_light"])
    board.alpha_composite(image)
    return board.convert("RGB")


class ImageViewer(tk.Toplevel):
    def __init__(self, parent, info, name):
        super().__init__(parent)
        self.title(f"{name} — ImgMtx")
        paint(self, bg=BG)
        window_size(self, 1000, 720)
        self.minsize(scaled(400), scaled(300))
        with Image.open(io.BytesIO(info.data)) as image:
            self.source = image.convert("RGBA")
        self.photo = None
        self.fit = True
        self.job = None
        bar = frame(self, bg=BG)
        bar.pack(fill="x", padx=18, pady=12)
        label(bar, f"{info.width:,} × {info.height:,} px", 10, MUTED).pack(side="left")
        self.toggle = button(bar, "View actual size", self.toggle_size)
        self.toggle.pack(side="right")
        area = frame(self, bg=BG)
        area.pack(fill="both", expand=True)
        self.canvas = canvas(area, bg=WELL, highlightthickness=0)
        vertical = tk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        horizontal = tk.Scrollbar(area, orient="horizontal", command=self.canvas.xview)
        for scrollbar in (vertical, horizontal):
            paint(scrollbar, bg=CARD, activebackground="hover", troughcolor=WELL, highlightbackground=BG)
        self.canvas.config(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.bind("<Configure>", self.resize)
        self.bind("<Escape>", lambda _e: self.destroy())

    def toggle_size(self):
        self.fit = not self.fit
        self.toggle.config(text="View actual size" if self.fit else "Fit to window")
        self.draw()

    def resize(self, _event=None):
        if self.job:
            self.after_cancel(self.job)
        self.job = self.after(80, self.draw)

    def draw(self):
        self.job = None
        image = self.source.copy()
        w, h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if self.fit:
            image.thumbnail((w, h), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(checkerboard(image, palette(self)), master=self)
        self.canvas.delete("all")
        self.canvas.create_image(max(w, image.width) / 2, max(h, image.height) / 2, image=self.photo)
        self.canvas.config(scrollregion=(0, 0, max(w, image.width), max(h, image.height)))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.theme_name = "light"
        self.palette = PALETTES[self.theme_name]
        self.key_format = tk.StringVar(self, value="custom")
        global SCALE
        SCALE = self.winfo_fpixels("1i") / 96
        self.title("ImgMtx")
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "ImgMtx.ico"
        if icon_path.is_file():
            with Image.open(icon_path) as icon:
                self.app_icon = ImageTk.PhotoImage(icon.convert("RGBA"), master=self)
            self.iconphoto(True, self.app_icon)
        window_size(self, 1180, 820)
        self.minsize(min(scaled(960), self.winfo_screenwidth() - scaled(50)), min(scaled(650), self.winfo_screenheight() - scaled(85)))
        paint(self, bg=BG)
        self.option_add("*Font", (FONT, 10))
        self.original = None
        self.original_path = None
        self.hidden = None
        self.hidden_path = None
        self.key_data = None
        self.key_path = None
        self.result = None
        self.mode = "create"
        self.busy = False
        self.jobs = queue.Queue()
        self._build()
        self.after(80, self._poll)
        self.bind("<Control-o>", lambda _e: self.choose_original() if not self.busy else None)
        self.bind("<Control-Shift-O>", lambda _e: self.choose_second() if not self.busy else None)
        self.bind("<Control-s>", lambda _e: self.save_result() if not self.busy else None)
        self.bind("<Return>", lambda _e: self.run() if str(self.action.cget("state")) == "normal" else None)

    def _build(self):
        main = frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=scaled(30), pady=scaled(18))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)
        masthead = frame(main, bg=BG)
        masthead.grid(row=0, column=0, sticky="ew", pady=(0, scaled(12)))
        mark = canvas(masthead, bg=BG, width=scaled(39), height=scaled(35), highlightthickness=0)
        self.mark = mark
        mark.pack(side="left", padx=(0, scaled(10)))
        self._draw_mark()
        label(masthead, "ImgMtx", 23, family=DISPLAY).pack(side="left")
        label(masthead, "IMAGE PAIRING TOOL", 9, MUTED, family=MONO).pack(side="left", padx=scaled(21))
        self.reset = button(masthead, "Clear workspace", self.clear)
        self.reset.pack(side="right")
        button(masthead, "How it works", self.help).pack(side="right", padx=(0, scaled(8)))
        self.theme_toggle = button(masthead, "Dark mode", self.toggle_theme)
        self.theme_toggle.pack(side="right", padx=(0, scaled(8)))

        navigation = frame(main, bg=BG)
        navigation.grid(row=1, column=0, sticky="ew")
        navigation.columnconfigure(2, weight=1)
        self.create_tab = button(navigation, "Create a key", lambda: self.switch("create"))
        self.create_tab.grid(row=0, column=0, sticky="ew")
        self.reveal_tab = button(navigation, "Reveal an image", lambda: self.switch("reveal"))
        self.reveal_tab.grid(row=0, column=1, sticky="ew", padx=(scaled(12), 0))
        label(navigation, "PNG  /  .imgkey  /  .txt", 9, MUTED, family=MONO).grid(row=0, column=2, sticky="e")
        self.create_rule = frame(navigation, bg=ACCENT, height=scaled(3))
        self.create_rule.grid(row=1, column=0, sticky="ew", pady=(scaled(6), 0))
        self.reveal_rule = frame(navigation, bg=EDGE, height=scaled(3))
        self.reveal_rule.grid(row=1, column=1, sticky="ew", padx=(scaled(12), 0), pady=(scaled(6), 0))
        frame(navigation, bg=EDGE, height=1).grid(row=1, column=2, sticky="sew")

        heading_row = frame(main, bg=BG)
        heading_row.grid(row=2, column=0, sticky="ew", pady=(scaled(15), scaled(4)))
        self.heading = label(heading_row, "Pair two images. Keep one key.", 18, family=DISPLAY, anchor="w")
        self.heading.pack(side="left")
        self.equation = label(heading_row, "A + B = KEY", 10, ACCENT, family=MONO)
        self.equation.pack(side="right")
        self.description = label(main, "Choose the original PNG and the image you want to reveal with it.", 10, MUTED, anchor="w")
        self.description.grid(row=3, column=0, sticky="ew", pady=(0, scaled(16)))
        self.cards = frame(main, bg=BG)
        self.cards.grid(row=4, column=0, sticky="nsew")
        self.cards.columnconfigure(0, weight=1, uniform="card")
        self.cards.columnconfigure(2, weight=1, uniform="card")
        self.cards.rowconfigure(0, weight=1)
        self.left = Preview(self.cards, "A", "Original image", "Keep this exact file for revealing later.", self.choose_original)
        self.left.grid(row=0, column=0, sticky="nsew")
        self.spine = canvas(self.cards, bg=BG, width=scaled(66), highlightthickness=0)
        self.spine_job = None
        self.spine.grid(row=0, column=1, sticky="ns")
        self.spine.bind("<Configure>", self._schedule_spine)
        self.left.canvas.bind("<Configure>", self._schedule_spine, add="+")
        self.right = Preview(self.cards, "B", "Hidden image", "The PNG your key will reconstruct.", self.choose_second)
        self.right.grid(row=0, column=2, sticky="nsew")

        self.key_bar = frame(main, bg=CARD, highlightbackground=EDGE, highlightthickness=1)
        self.key_bar.grid(row=5, column=0, sticky="ew", pady=(scaled(14), 0))
        self.key_bar.configure(height=scaled(47))
        self.key_bar.pack_propagate(False)
        self.key_label = label(self.key_bar, "KEY FORMAT", 9, ACCENT, family=MONO)
        self.key_label.pack(side="left", padx=(scaled(16), scaled(20)))
        self.key_name = label(self.key_bar, "No key file selected", 10, MUTED, anchor="w", width=1)
        self.key_name.pack(side="left", fill="x", expand=True, padx=(0, scaled(8)))
        self.key_button = button(self.key_bar, "Choose key file", self.choose_second)
        self.key_hint = frame(self.key_bar, bg=CARD)
        self.format_custom = self._format_choice(self.key_hint, "Custom (.imgkey)", "custom")
        self.format_custom.pack(side="left", padx=(0, scaled(16)))
        self.format_png = self._format_choice(self.key_hint, "Image (.png)", "png")
        self.format_png.pack(side="left")
        self.key_hint.pack(side="right", padx=scaled(16))
        self.key_guidance = label(self.key_bar, "Store the key as", 10, MUTED)
        self.key_guidance.pack(side="left")
        self.key_name.pack_forget()

        self.note = label(main, "Original files stay untouched. All processing stays on this device.", 9, MUTED, anchor="w")
        self.note.grid(row=6, column=0, sticky="ew", pady=(scaled(8), scaled(10)))
        frame(main, bg=EDGE, height=1).grid(row=7, column=0, sticky="ew")
        action_bar = frame(main, bg=BG)
        action_bar.grid(row=8, column=0, sticky="ew", pady=(scaled(12), 0))
        self.status = label(action_bar, "Choose two PNGs to begin.", 10, MUTED, anchor="w", justify="left", wraplength=scaled(600))
        self.status.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.save = button(action_bar, "Save PNG", self.save_result)
        self.action = button(action_bar, "Create key file", self.run, primary=True)
        self.action.pack(side="right")
        self._update_controls()

    def _format_choice(self, parent, text, value):
        choice = tk.Radiobutton(parent, text=text, variable=self.key_format, value=value,
                                command=self._format_changed,
                                font=(FONT, 10), cursor="hand2", bd=0, padx=scaled(4),
                                pady=scaled(3), highlightthickness=1, takefocus=True)
        return paint(choice, bg=CARD, fg=TEXT, selectcolor=CARD,
                     activebackground=CARD, activeforeground=TEXT,
                     disabledforeground="disabled", highlightbackground=CARD, highlightcolor=TEXT)

    def _format_changed(self):
        if self.mode == "create":
            self.note.config(text="Keep the key PNG's pixels unchanged. Original files stay untouched."
                             if self.key_format.get() == "png" else
                             "Original files stay untouched. All processing stays on this device.")

    def _draw_mark(self):
        self.mark.delete("all")
        self.mark.create_rectangle(scaled(2), scaled(2), scaled(25), scaled(25), outline=tone(self, TEXT), width=scaled(2))
        self.mark.create_rectangle(scaled(12), scaled(12), scaled(35), scaled(35), outline=tone(self, ACCENT), width=scaled(2))
        self.mark.create_rectangle(scaled(13), scaled(13), scaled(24), scaled(24), fill=tone(self, ACCENT), outline="")

    def toggle_theme(self):
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self.palette = PALETTES[self.theme_name]
        retheme(self)
        self.theme_toggle.config(text="Light mode" if self.theme_name == "dark" else "Dark mode")
        self._draw_mark()
        self.left.draw()
        self.right.draw()
        self._draw_spine()
        for window in self.winfo_children():
            if isinstance(window, ImageViewer):
                window.draw()
        self._update_controls()

    def _schedule_spine(self, _event=None):
        if self.spine_job:
            self.after_cancel(self.spine_job)
        self.spine_job = self.after_idle(self._draw_spine)

    def _draw_spine(self):
        self.spine_job = None
        self.spine.delete("all")
        cx = self.spine.winfo_width() / 2
        # Align this quiet connector with the centre of the image wells.
        cy = self.left.canvas.winfo_y() + self.left.canvas.winfo_height() / 2
        radius = scaled(13)
        self.spine.create_line(0, cy, cx - radius, cy, fill=tone(self, EDGE))
        self.spine.create_line(cx + radius, cy, cx * 2, cy, fill=tone(self, EDGE))
        self.spine.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=tone(self, EDGE))
        self.spine.create_line(cx - scaled(5), cy, cx + scaled(5), cy, fill=tone(self, ACCENT), width=scaled(2))
        self.spine.create_line(cx, cy - scaled(5), cx, cy + scaled(5), fill=tone(self, ACCENT), width=scaled(2))

    def tell(self, text, error=False, success=False):
        self.status.config(text=f"Error: {text}" if error else text)
        paint(self.status, fg=ERROR if error else "success" if success else MUTED)

    def _update_controls(self):
        for control in (self.left.choose, self.right.choose, self.key_button, self.reset, self.create_tab, self.reveal_tab, self.format_custom, self.format_png):
            control.config(state="disabled" if self.busy else "normal")
        ready = self.original and (self.hidden if self.mode == "create" else self.key_data)
        self.action.config(state="normal" if ready and not self.busy else "disabled")
        self.save.config(state="normal" if self.result and not self.busy else "disabled")
        paint(self.action, bg=ACCENT if ready and not self.busy else "inactive", fg=INK if ready and not self.busy else MUTED, highlightbackground=ACCENT if ready and not self.busy else EDGE)
        for tab, rule, selected in ((self.create_tab, self.create_rule, self.mode == "create"), (self.reveal_tab, self.reveal_rule, self.mode == "reveal")):
            tab.config(highlightthickness=1, font=(FONT, 10, "bold" if selected else "normal"))
            paint(tab, bg=BG, fg=TEXT if selected else MUTED, highlightbackground=BG)
            paint(rule, bg=ACCENT if selected else EDGE)

    def _background(self, operation, callback, message):
        if self.busy:
            return
        self.busy = True
        self.tell(message)
        self._update_controls()

        def worker():
            try:
                self.jobs.put((callback, operation(), None))
            except Exception as exc:
                self.jobs.put((callback, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            callback, result, error = self.jobs.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if error:
                self.tell(str(error) if isinstance(error, (ImgMtxError, OSError)) else "Unable to process this file. Please choose a valid PNG or ImgMtx key.", error=True)
            else:
                try:
                    callback(result)
                except (ImgMtxError, OSError) as exc:
                    self.tell(str(exc), error=True)
            self._update_controls()
        self.after(80, self._poll)

    def choose_original(self):
        path = filedialog.askopenfilename(parent=self, title="Choose the original PNG", filetypes=[("PNG image", "*.png")])
        if not path:
            return

        def loaded(info):
            self.original, self.original_path = info, Path(path)
            self.left.set_image(info, Path(path).name)
            self._invalidate_result()
            self.tell("Original loaded. Choose a hidden PNG." if self.mode == "create" else "Original loaded. Choose its matching key file.")

        self._background(lambda: read_png(path), loaded, "Reading original PNG…")

    def choose_second(self):
        if self.mode == "reveal":
            path = filedialog.askopenfilename(parent=self, title="Choose the ImgMtx key file", filetypes=[("ImgMtx keys", "*.imgkey *.png *.txt"), ("PNG image key", "*.png"), ("All files", "*.*")])
            if not path:
                return

            def loaded(data):
                self.key_data, self.key_path = data, Path(path)
                self.key_name.config(text=f"{Path(path).name}   ·   {size_text(len(data))}")
                paint(self.key_name, fg=TEXT)
                self._invalidate_result()
                self.tell("Key loaded. Ready to reveal." if self.original else "Key loaded. Choose the matching original PNG.")

            self._background(lambda: read_key(path), loaded, "Reading key file…")
        else:
            path = filedialog.askopenfilename(parent=self, title="Choose the hidden PNG", filetypes=[("PNG image", "*.png")])
            if not path:
                return

            def loaded(info):
                self.hidden, self.hidden_path = info, Path(path)
                self.right.set_image(info, Path(path).name)
                self.tell("Both images loaded. Ready to create your key." if self.original else "Hidden image loaded. Choose the original PNG.")

            self._background(lambda: read_png(path), loaded, "Reading hidden PNG…")

    def _invalidate_result(self):
        self.result = None
        if self.mode == "reveal":
            self.right.set_image(None, "")
            self.right.name.config(text="Hidden image awaits its key")
            self.right.meta.config(text="Double-click a revealed image to enlarge")
            self.right.empty_state("Waiting for the key", "Choose the matching key file below", can_choose=False)

    def switch(self, mode):
        if self.busy or mode == self.mode:
            return
        self.mode = mode
        self.result = None
        self.key_label.config(text="KEY FILE" if mode == "reveal" else "KEY FORMAT")
        if mode == "reveal":
            self.heading.config(text="The other image is in the key.")
            self.equation.config(text="A + KEY = B")
            self.description.config(text="Open the unchanged original and its key file. The hidden PNG appears on the right.")
            self.right.title.config(text="Revealed image")
            self.right.subtitle.config(text="Your hidden image will appear here.")
            self.right.choose.grid_remove()
            self._invalidate_result()
            self.key_guidance.pack_forget()
            self.key_hint.pack_forget()
            self.key_name.pack(side="left", fill="x", expand=True, padx=(0, scaled(8)))
            self.key_button.pack(side="right", padx=scaled(8), pady=scaled(3))
            self.save.pack(side="right", padx=(0, scaled(9)), after=self.action)
            self.action.config(text="Reveal image")
            self.tell("Choose the original PNG and its matching key file.")
            self.note.config(text="Recovery preserves the hidden PNG exactly. Double-click a preview to enlarge.")
        else:
            self.heading.config(text="Pair two images. Keep one key.")
            self.equation.config(text="A + B = KEY")
            self.description.config(text="Choose the original PNG and the image you want to reveal with it.")
            self.right.title.config(text="Hidden image")
            self.right.subtitle.config(text="The image your key will reveal.")
            self.right.set_image(self.hidden, self.hidden_path.name if self.hidden_path else "")
            self.right.empty_state("Hidden PNG", "Choose a file below, or click here")
            self.right.choose.grid()
            self.key_name.pack_forget()
            self.key_button.pack_forget()
            self.key_hint.pack(side="right", padx=scaled(16))
            self.key_guidance.pack(side="left")
            self.save.pack_forget()
            self.action.config(text="Create key file")
            self.tell("Choose two PNGs to begin." if not self.original or not self.hidden else "Both images loaded. Ready to create your key.")
            self.note.config(text="Original files stay untouched. All processing stays on this device.")
            self._format_changed()
        self._update_controls()

    def run(self):
        if self.busy or not self.original:
            return
        if self.mode == "create" and self.hidden:
            original, hidden = self.original, self.hidden
            self._background(lambda: create_key(original, hidden), self._save_key, "Creating your key…")
        elif self.mode == "reveal" and self.key_data:
            self._invalidate_result()
            original, key_data = self.original, self.key_data

            def revealed(info):
                self.result = info
                self.right.set_image(info, "Hidden image · recovered")
                self.tell("Image revealed. Save a PNG or double-click to enlarge.", success=True)

            self._background(lambda: reveal_image(original, key_data), revealed, "Checking original and reconstructing hidden image…")

    def _save_key(self, data):
        stem = self.original_path.stem if self.original_path else "image"
        image_key = self.key_format.get() == "png"
        extension = ".png" if image_key else ".imgkey"
        initialfile = f"{stem}.key.png" if image_key else f"{stem}.imgkey"
        filetypes = ([("PNG image key", "*.png")] if image_key else
                     [("ImgMtx binary key", "*.imgkey"), ("Text key (Base64)", "*.txt")])
        path = filedialog.asksaveasfilename(parent=self, title="Save a new secret key file", defaultextension=extension, initialfile=initialfile, confirmoverwrite=False, filetypes=filetypes)
        if not path:
            self.tell("Save cancelled. Your input images are unchanged.")
            return
        protected = tuple(p for p in (self.original_path, self.hidden_path, self.key_path) if p)

        def write_key():
            suffix = Path(path).suffix.lower()
            if suffix == ".png":
                payload = encode_png_key(data)
            elif suffix == ".txt":
                payload = encode_text_key(data)
            elif suffix == ".imgkey":
                payload = data
            else:
                raise ImgMtxError("Use .png for an image key, or .imgkey / .txt for a custom key.")
            write_new_file(path, payload, protected_paths=protected)
            return len(payload)

        def saved(length):
            self.tell(f"Key saved: {Path(path).name} ({size_text(length)}). Keep it with the original.", success=True)

        self._background(write_key, saved, "Saving key file…")

    def save_result(self):
        if self.busy or not self.result or self.mode != "reveal":
            return
        path = filedialog.asksaveasfilename(parent=self, title="Save the revealed image as a new PNG", defaultextension=".png", initialfile="revealed.png", confirmoverwrite=False, filetypes=[("PNG image", "*.png")])
        if not path:
            return
        protected = tuple(p for p in (self.original_path, self.hidden_path, self.key_path) if p)
        data = self.result.data
        self._background(lambda: write_new_file(path, data, protected_paths=protected), lambda _: self.tell(f"Revealed PNG saved: {Path(path).name}", success=True), "Saving revealed PNG…")

    def clear(self):
        if self.busy:
            return
        self.original = self.hidden = self.result = self.key_data = None
        self.original_path = self.hidden_path = self.key_path = None
        self.left.set_image(None, "")
        self.right.set_image(None, "")
        self.key_name.config(text="No key file selected")
        paint(self.key_name, fg=MUTED)
        self._invalidate_result()
        self.tell("Workspace cleared. Choose files to begin.")
        self._update_controls()

    def help(self):
        window = tk.Toplevel(self)
        window.title("How ImgMtx works")
        paint(window, bg=CARD)
        window.resizable(False, False)
        label(window, f"ImgMtx {__version__}", 18, family=DISPLAY).pack(anchor="w", padx=25, pady=(24, 16))
        text = (
            "CREATE A KEY\nSelect an original PNG and a hidden PNG, then save a key file.\n"
            "The two images can have different sizes and transparency.\n\n"
            "REVEAL AN IMAGE\nSelect the exact original PNG and its key, then click Reveal image.\n"
            "Save PNG exports the hidden file exactly, including its metadata.\n"
            "Double-click any image preview for a larger view.\n\n"
            "KEEP THE EXACT ORIGINAL\nRe-saving or editing the original changes its contents and invalidates\n"
            "the match. ImgMtx never overwrites an existing file.\n\n"
            "KEY FILES\nChoose Custom (.imgkey) or Image (.png) before creating a key.\n"
            "Image keys are ordinary PNGs with key data in their pixels.\n"
            "Do not edit, resize, or convert an image key to JPEG.\n"
            "Existing .imgkey and .txt keys are still supported.\n"
            "A key can be as large as the hidden image. Keep it private.\n"
            "This is image mapping, not password-protected encryption. Anyone\n"
            "with both files can reveal the image. Public originals add no secrecy.\n\n"
            "LOCAL BY DESIGN\nFiles are processed in memory. Nothing is uploaded or auto-saved.\n"
            "PNG only. Maximum 64 MB and 25 million pixels per image.\n\n"
            "SHORTCUTS\nCtrl+O: original   ·   Ctrl+Shift+O: hidden/key   ·   Ctrl+S: save PNG"
        )
        label(window, text, 10, MUTED, justify="left").pack(anchor="w", padx=25)
        button(window, "Got it", window.destroy, primary=True).pack(anchor="e", padx=25, pady=24)
        window.transient(self)


def main():
    # Use native display scaling when Windows exposes the API.
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    App().mainloop()


if __name__ == "__main__":
    main()
