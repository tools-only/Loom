#!/usr/bin/env python3
"""
Loom Desktop Float - native Windows floating capture window.

The window is intentionally small: paste a URL, press Enter, and the backend
receives enough structure to analyze and classify the resource on its own.
"""

from __future__ import annotations

import json
import os
import re
import threading
import tkinter as tk
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


FLOAT_W = 66
FLOAT_H = 44
PANEL_W = 382
PANEL_H_COMPACT = 246
PANEL_H_DETAILS = 340
LOOM_HOST = "http://localhost:3000"
CAPTURE_URL = f"{LOOM_HOST}/channels/capture"
DEFAULT_DOMAIN = "loom-fin"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "LoomDesktopFloat"
CONFIG_FILE = CONFIG_DIR / "config.json"

URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)

COLORS = {
    "transparent": "#010101",
    "float": "#18201D",
    "float_hover": "#21332D",
    "panel": "#F7F6F1",
    "surface": "#FFFFFF",
    "surface_soft": "#EFEEE7",
    "ink": "#171A1C",
    "muted": "#6F746F",
    "line": "#D8D5C8",
    "accent": "#0F766E",
    "accent_hover": "#115E59",
    "accent_soft": "#DDEEEA",
    "ok": "#0F7A54",
    "error": "#B42318",
}

FONT = "Microsoft YaHei UI"


def clamp_window_position(x, y, width, height, bounds):
    left, top, right, bottom = bounds
    max_x = max(left, right - width)
    max_y = max(top, bottom - height)
    return (
        min(max(int(x), left), max_x),
        min(max(int(y), top), max_y),
    )


def extract_first_url(text: str) -> str:
    match = URL_RE.search(text or "")
    if not match:
        return ""
    return match.group(0).rstrip(").,;]}>")


def infer_channel(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    if not host:
        return ""
    if host in {"x.com", "twitter.com"} or host.endswith(".twitter.com"):
        return "x"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "reddit.com" in host:
        return "reddit"
    if "substack.com" in host:
        return "substack"
    if "github.com" in host:
        return "github"
    if "sec.gov" in host:
        return "filing"
    return "web"


def infer_title(raw_text: str, url: str) -> str:
    for line in str(raw_text or "").splitlines():
        line = line.strip()
        if line and not URL_RE.fullmatch(line):
            return line[:160]
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else (host or "Captured resource")


def split_tags(value) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value or "").split(",")
    tags: list[str] = []
    for item in raw:
        tag = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(item).strip().lower()).strip("-")
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 12:
            break
    return tags


def build_capture_payload(
    raw_text: str,
    *,
    title: str = "",
    note: str = "",
    tags=None,
    domain: str = DEFAULT_DOMAIN,
) -> dict:
    raw = str(raw_text or "").strip()
    url = extract_first_url(raw)
    inferred_title = title.strip() or infer_title(raw, url)
    merged_tags = split_tags(tags)
    if domain and domain not in merged_tags:
        merged_tags.insert(0, domain)
    if note.strip():
        raw_for_text = f"{raw}\n\n{note.strip()}" if raw else note.strip()
    else:
        raw_for_text = raw
    channel = infer_channel(url)
    is_link = bool(url)
    return {
        "url": url,
        "title": inferred_title,
        "text": raw_for_text,
        "note": note.strip(),
        "tags": merged_tags,
        "channel": channel,
        "domain": domain,
        "trust_tier": "F",
        "resource_kind": "link" if is_link else "note",
        "intent_hint": (
            "Analyze this resource for reusable Loom evaluation signals; "
            "treat social sources as hypotheses unless verified."
        ),
        "value_signal": inferred_title or url or raw[:120],
        "source_platform": channel,
    }


def load_config():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text("utf-8"))
    except Exception:
        pass
    return {}


def save_config(cfg):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), "utf-8")
    except Exception:
        pass


def post_async(payload, callback):
    """POST to Loom capture endpoint in a background thread."""

    def _run():
        try:
            data = json.dumps(payload).encode("utf-8")
            req = Request(
                CAPTURE_URL,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            resp = urlopen(req, timeout=10)
            body = json.loads(resp.read().decode("utf-8"))
            ok = resp.status == 200 and body.get("ok", False)
            resource = body.get("resource", {}) if isinstance(body, dict) else {}
            msg = body.get("error") or resource.get("resource_id") or "Saved"
            callback(ok, msg)
        except URLError as exc:
            err = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            callback(False, f"Loom is not reachable. {err}")
        except Exception as exc:
            callback(False, str(exc))

    threading.Thread(target=_run, daemon=True).start()


class LoomDesktopFloat:
    """Desktop floating capture app."""

    def __init__(self, start_mainloop: bool = True):
        self.root = tk.Tk()
        self.root.title("Loom Capture")
        self._details_visible = False
        self._placeholder = "Paste URL"
        self._has_placeholder = True
        self._setup_window()
        self._build_float()
        self._build_panel()
        self._load_position()
        self._show_float()
        if start_mainloop:
            self.root.mainloop()

    def _setup_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-toolwindow", True)
        try:
            self.root.wm_attributes("-transparentcolor", COLORS["transparent"])
        except Exception:
            pass
        self.root.configure(bg=COLORS["transparent"])
        self._set_window_geometry(FLOAT_W, FLOAT_H)
        self._is_expanded = False
        self._dragging = False
        self._drag_x = 0
        self._drag_y = 0
        self._win_x = 0
        self._win_y = 0

    def _build_float(self):
        self.float_frame = tk.Frame(
            self.root,
            width=FLOAT_W,
            height=FLOAT_H,
            bg=COLORS["transparent"],
            highlightthickness=0,
        )
        self.float_frame.place(x=0, y=0)

        self.canvas = tk.Canvas(
            self.float_frame,
            width=FLOAT_W,
            height=FLOAT_H,
            bg=COLORS["transparent"],
            highlightthickness=0,
        )
        self.canvas.pack()
        self._draw_float(False)

        self.canvas.bind("<Button-1>", self._on_float_press)
        self.canvas.bind("<B1-Motion>", self._on_float_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_float_release)
        self.canvas.bind("<Enter>", lambda _event: self._draw_float(True))
        self.canvas.bind("<Leave>", lambda _event: self._draw_float(False))

    def _draw_float(self, hovered: bool):
        self.canvas.delete("all")
        fill = COLORS["float_hover"] if hovered else COLORS["float"]
        self._round_rect(self.canvas, 3, 4, FLOAT_W - 3, FLOAT_H - 3, 8, fill=fill, outline="")
        self.canvas.create_oval(14, 15, 22, 23, fill=COLORS["accent"], outline="")
        self.canvas.create_text(
            41,
            22,
            text="+",
            fill="#FFFFFF",
            font=(FONT, 17, "bold"),
        )

    def _build_panel(self):
        self.panel = tk.Frame(self.root, bg=COLORS["panel"], highlightthickness=0)
        self.panel.place(x=0, y=0, width=PANEL_W, height=PANEL_H_DETAILS)
        self.panel.place_forget()
        self._bind_panel_drag(self.panel)

        header = tk.Frame(self.panel, bg=COLORS["panel"], cursor="fleur")
        header.place(x=18, y=14, width=PANEL_W - 36, height=32)
        self._bind_panel_drag(header)

        title = tk.Label(
            header,
            text="Capture",
            bg=COLORS["panel"],
            fg=COLORS["ink"],
            font=(FONT, 13, "bold"),
            cursor="fleur",
        )
        title.pack(side="left")
        self._bind_panel_drag(title)

        close = tk.Button(
            header,
            text="x",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            bd=0,
            activebackground=COLORS["surface_soft"],
            activeforeground=COLORS["ink"],
            cursor="hand2",
            font=(FONT, 12),
            command=self._collapse,
        )
        close.pack(side="right")

        self._input_shell = tk.Frame(
            self.panel,
            bg=COLORS["surface"],
            highlightthickness=1,
            highlightbackground=COLORS["line"],
        )
        self._input_shell.place(x=18, y=58, width=PANEL_W - 36, height=48)

        self._input_var = tk.StringVar()
        self._input = tk.Entry(
            self._input_shell,
            textvariable=self._input_var,
            bd=0,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            insertbackground=COLORS["accent"],
            font=(FONT, 11),
        )
        self._input.place(x=14, y=12, width=PANEL_W - 64, height=24)
        self._input.insert(0, self._placeholder)
        self._input.bind("<FocusIn>", self._on_input_focus)
        self._input.bind("<FocusOut>", self._on_input_blur)
        self._input.bind("<KeyRelease>", self._on_input_key)
        self._input.bind("<Return>", lambda _event: self._submit())

        self._details_btn = tk.Button(
            self.panel,
            text="Details",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            bd=0,
            activebackground=COLORS["panel"],
            activeforeground=COLORS["accent"],
            cursor="hand2",
            anchor="w",
            font=(FONT, 9),
            command=self._toggle_details,
        )
        self._details_btn.place(x=18, y=114, width=80, height=24)

        self._details_frame = tk.Frame(self.panel, bg=COLORS["panel"])
        self._details_frame.place(x=18, y=142, width=PANEL_W - 36, height=112)
        self._details_frame.place_forget()

        tk.Label(
            self._details_frame,
            text="Title",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=(FONT, 8),
        ).place(x=0, y=0)
        self._title_var = tk.StringVar()
        self._title = tk.Entry(
            self._details_frame,
            textvariable=self._title_var,
            bd=0,
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            font=(FONT, 10),
        )
        self._title.place(x=0, y=20, width=PANEL_W - 36, height=30)

        tk.Label(
            self._details_frame,
            text="Note",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=(FONT, 8),
        ).place(x=0, y=58)
        self._note = tk.Text(
            self._details_frame,
            bd=0,
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            insertbackground=COLORS["accent"],
            font=(FONT, 9),
            wrap="word",
            height=2,
        )
        self._note.place(x=0, y=78, width=PANEL_W - 36, height=34)

        self._submitting = False
        self._submit_btn = tk.Label(
            self.panel,
            text="Save",
            bg=COLORS["accent"],
            fg="#FFFFFF",
            cursor="hand2",
            font=(FONT, 10, "bold"),
            padx=18,
            pady=6,
        )
        self._submit_btn.place(x=18, y=PANEL_H_COMPACT - 88, width=PANEL_W - 36, height=38)
        self._submit_btn.bind("<Button-1>", lambda _event: self._submit())

        self._status = tk.Label(
            self.panel,
            text="Ready",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            anchor="center",
            font=(FONT, 9),
        )
        self._status.place(x=18, y=PANEL_H_COMPACT - 42, width=PANEL_W - 36, height=24)

    def _show_float(self):
        self._is_expanded = False
        self.panel.place_forget()
        self.float_frame.place(x=0, y=0)
        self._set_window_geometry(FLOAT_W, FLOAT_H)
        self.root.attributes("-topmost", True)

    def _expand(self):
        self._is_expanded = True
        self.float_frame.place_forget()
        self._resize_panel()
        self.panel.place(x=0, y=0, width=PANEL_W, height=self._panel_height())
        self.root.attributes("-topmost", True)
        self.root.lift()
        self._try_prefill_from_clipboard()
        self._input.focus_set()
        self._input.icursor("end")

    def _collapse(self):
        self._clear_input()
        self._show_float()
        self._save_position()

    def _on_float_press(self, event):
        if not self._is_expanded:
            self._begin_drag(event)

    def _on_float_drag(self, event):
        if not self._is_expanded:
            self._drag_window(event, FLOAT_W, FLOAT_H)

    def _on_float_release(self, event):
        if not self._is_expanded:
            if not self._dragging:
                self._expand()
            else:
                self._save_position()
            self._dragging = False

    def _bind_panel_drag(self, widget):
        widget.bind("<Button-1>", self._on_panel_press)
        widget.bind("<B1-Motion>", self._on_panel_drag)
        widget.bind("<ButtonRelease-1>", self._on_panel_release)

    def _on_panel_press(self, event):
        if self._is_expanded:
            self._begin_drag(event)

    def _on_panel_drag(self, event):
        if self._is_expanded:
            self._drag_window(event, PANEL_W, self._panel_height())

    def _on_panel_release(self, _event):
        if self._is_expanded and self._dragging:
            self._save_position()
        self._dragging = False

    def _on_input_focus(self, _event):
        if self._has_placeholder:
            self._input.delete(0, "end")
            self._input.config(fg=COLORS["ink"])
            self._has_placeholder = False

    def _on_input_blur(self, _event):
        if not self._input_var.get().strip():
            self._input.delete(0, "end")
            self._input.insert(0, self._placeholder)
            self._input.config(fg=COLORS["muted"])
            self._has_placeholder = True

    def _on_input_key(self, _event):
        raw = self._input_value()
        if extract_first_url(raw):
            self._show_status("", "URL detected")
        elif raw:
            self._show_status("", "Note detected")
        else:
            self._show_status("", "Ready")

    def _paste_clipboard(self):
        try:
            value = self.root.clipboard_get().strip()
        except Exception:
            value = ""
        if value:
            self._set_input(value)
            self._on_input_key(None)

    def _try_prefill_from_clipboard(self):
        if self._input_value():
            return
        try:
            value = self.root.clipboard_get().strip()
        except Exception:
            return
        url = extract_first_url(value)
        if url:
            self._set_input(url)
            self._show_status("", "URL detected")

    def _toggle_details(self):
        self._details_visible = not self._details_visible
        if self._details_visible:
            self._details_frame.place(x=18, y=142, width=PANEL_W - 36, height=112)
            self._details_btn.config(text="Hide")
        else:
            self._details_frame.place_forget()
            self._details_btn.config(text="Details")
        self._resize_panel()

    def _panel_height(self):
        return PANEL_H_DETAILS if self._details_visible else PANEL_H_COMPACT

    def _resize_panel(self):
        height = self._panel_height()
        self._set_window_geometry(PANEL_W, height)
        self.panel.place_configure(width=PANEL_W, height=height)
        self._submit_btn.place_configure(y=height - 88)
        self._status.place_configure(y=height - 42)

    def _submit(self):
        if self._submitting:
            return
        raw = self._input_value()
        if not raw:
            self._show_status("error", "Paste a URL")
            return
        note = self._note.get("1.0", "end-1c").strip() if self._details_visible else ""
        payload = build_capture_payload(
            raw,
            title=self._title_var.get(),
            note=note,
            tags=[],
            domain=DEFAULT_DOMAIN,
        )
        self._submitting = True
        self._submit_btn.config(text="Saving", bg=COLORS["accent_hover"])
        self._show_status("", "Saving")
        post_async(payload, self._on_result)

    def _on_result(self, ok, msg):
        self.root.after(0, lambda: self._handle_result(ok, msg))

    def _handle_result(self, ok, msg):
        self._submitting = False
        self._submit_btn.config(text="Save", bg=COLORS["accent"])
        if ok:
            self._show_status("ok", "Saved")
            self.root.after(900, self._collapse)
        else:
            self._show_status("error", msg)

    def _show_status(self, kind, msg):
        color = COLORS["ok"] if kind == "ok" else COLORS["error"] if kind == "error" else COLORS["muted"]
        self._status.config(text=msg, fg=color)

    def _input_value(self):
        return "" if self._has_placeholder else self._input_var.get().strip()

    def _set_input(self, value):
        self._input.delete(0, "end")
        self._input.insert(0, value)
        self._input.config(fg=COLORS["ink"])
        self._has_placeholder = False

    def _clear_input(self):
        self._input.delete(0, "end")
        self._input.insert(0, self._placeholder)
        self._input.config(fg=COLORS["muted"])
        self._has_placeholder = True
        self._title_var.set("")
        self._note.delete("1.0", "end")
        self._show_status("", "Ready")
        if self._details_visible:
            self._toggle_details()

    def _begin_drag(self, event):
        self._dragging = False
        self._drag_x = event.x_root
        self._drag_y = event.y_root
        self._win_x = self.root.winfo_x()
        self._win_y = self.root.winfo_y()

    def _drag_window(self, event, width, height):
        dx = event.x_root - self._drag_x
        dy = event.y_root - self._drag_y
        if abs(dx) > 3 or abs(dy) > 3:
            self._dragging = True
            self._set_window_geometry(width, height, self._win_x + dx, self._win_y + dy)

    def _screen_bounds(self):
        try:
            left = self.root.winfo_vrootx()
            top = self.root.winfo_vrooty()
            width = self.root.winfo_vrootwidth()
            height = self.root.winfo_vrootheight()
            if width > 0 and height > 0:
                return (left, top, left + width, top + height)
        except Exception:
            pass
        return (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())

    def _set_window_geometry(self, width, height, x=None, y=None):
        if x is None:
            x = self.root.winfo_x()
        if y is None:
            y = self.root.winfo_y()
        x, y = clamp_window_position(x, y, width, height, self._screen_bounds())
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _load_position(self):
        cfg = load_config()
        pos = cfg.get("position")
        if pos:
            self._set_window_geometry(
                FLOAT_W,
                FLOAT_H,
                pos.get("x", 0),
                pos.get("y", 0),
            )
        else:
            self._position_bottom_right()

    def _save_position(self):
        save_config({"position": {"x": self.root.winfo_x(), "y": self.root.winfo_y()}})

    def _position_bottom_right(self):
        left, top, right, bottom = self._screen_bounds()
        self._set_window_geometry(
            FLOAT_W,
            FLOAT_H,
            right - FLOAT_W - 40,
            bottom - FLOAT_H - 48,
        )

    @staticmethod
    def _round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, splinesteps=18, **kwargs)


def main():
    LoomDesktopFloat()


if __name__ == "__main__":
    main()
