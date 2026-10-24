"""Semantic colours shared by the work surface and its secondary windows."""

import tkinter as tk


LIGHT = {
    "bg": "#eeeee5", "card": "#f6f6ef", "edge": "#c4c7b9",
    "text": "#282b25", "muted": "#62675c", "accent": "#ad432c",
    "ink": "#fff9ef", "error": "#a32824", "success": "#38603c",
    "well": "#242822", "well_text": "#b8bdae", "well_title": "#e8eadd",
    "well_mark": "#89917e", "registration": "#7b8370",
    "hover": "#e2e5d8", "accent_hover": "#8f3422",
    "disabled": "#8a8e80", "inactive": "#daddcf",
    "checker_dark": "#d4d7cd", "checker_light": "#e8e9e0",
}
DARK = {
    "bg": "#20241f", "card": "#2b3028", "edge": "#4a5143",
    "text": "#eff0e5", "muted": "#b9bfae", "accent": "#e59b7b",
    "ink": "#201b17", "error": "#ffaaa0", "success": "#aaca95",
    "well": "#131710", "well_text": "#b8bdae", "well_title": "#e8eadd",
    "well_mark": "#89917e", "registration": "#7b8370",
    "hover": "#373f32", "accent_hover": "#efb298",
    "disabled": "#8b9481", "inactive": "#353d2f",
    "checker_dark": "#3a4036", "checker_light": "#4a5244",
}
PALETTES = {"light": LIGHT, "dark": DARK}


def palette(widget):
    return getattr(widget._root(), "palette", LIGHT)


def color(widget, role):
    return palette(widget)[role]


def paint(widget, **roles):
    """Set colours and retain their meaning for a later theme change."""
    assigned = getattr(widget, "_theme_roles", {}).copy()
    assigned.update(roles)
    widget._theme_roles = assigned
    widget.configure(**{option: color(widget, role) for option, role in roles.items()})
    return widget


def _surface(kind, parent, **options):
    roles = {option: options.pop(option) for option in
             ("bg", "highlightbackground", "highlightcolor") if option in options}
    return paint(kind(parent, **options), **roles)


def frame(parent, **options):
    options.setdefault("bg", "bg")
    return _surface(tk.Frame, parent, **options)


def canvas(parent, **options):
    options.setdefault("bg", "bg")
    return _surface(tk.Canvas, parent, **options)


def retheme(widget):
    """Recolour live widgets without recreating controls or their state."""
    roles = getattr(widget, "_theme_roles", {})
    if roles:
        paint(widget, **roles)
    for child in widget.winfo_children():
        retheme(child)
