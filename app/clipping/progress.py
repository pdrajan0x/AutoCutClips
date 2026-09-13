"""
clipping.progress — A single-line progress bar shared by the render pipeline.

The renderers used to print one line per percent, which buried the real output
under ~100 lines per stage. This draws one line and rewrites it in place.

Deliberately dependency-free: it is imported by modules (``ffmpeg_utils``) that
must stay clear of the heavy OpenCV/ML imports.
"""

import sys

BAR_WIDTH = 24

# Filled cells use a full block and empty cells a plain space. Do NOT switch the
# empty cell to a shade glyph such as "░": terminals (Colab's included) pull the
# shade characters from a different fallback font than the full block, so the two
# halves of the bar end up drawn at different heights.
FILLED_CHAR = "█"
EMPTY_CHAR = " "
ASCII_FILLED_CHAR = "#"


def _stream_supports(stream, text: str) -> bool:
    """True if *text* can be written to *stream* without an encoding error."""
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return True
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def render_bar(fraction: float, width: int = BAR_WIDTH, stream=None) -> str:
    """Render the ``███     `` body of a bar (no surrounding pipes)."""
    fraction = min(1.0, max(0.0, fraction))
    filled_char = FILLED_CHAR
    if stream is not None and not _stream_supports(stream, FILLED_CHAR):
        filled_char = ASCII_FILLED_CHAR
    filled = int(width * fraction)
    return filled_char * filled + EMPTY_CHAR * (width - filled)


def format_clock(seconds) -> str:
    """Format a duration as M:SS (or H:MM:SS past an hour)."""
    try:
        seconds = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "?"
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class ProgressBar:
    """
    A percentage bar that redraws a single terminal line.

    Only repaints when the whole rendered line changes, so a 30-minute render
    does not spam the notebook. Use as a context manager to guarantee the
    trailing newline even if the caller raises.
    """

    def __init__(self, total, label: str, show_clock: bool = True, stream=None):
        try:
            self.total = float(total)
        except (TypeError, ValueError):
            self.total = 0.0
        self.label = label
        self.show_clock = show_clock
        self.stream = stream if stream is not None else sys.stdout
        self._prefix = "⏳ " if _stream_supports(self.stream, "⏳") else ""
        self._last_line = None
        self._closed = False

    def _render(self, current: float) -> str:
        if self.total > 0:
            fraction = min(1.0, max(0.0, current / self.total))
        else:
            fraction = 1.0
        percent = int(fraction * 100)
        bar = render_bar(fraction, BAR_WIDTH, self.stream)

        line = f"{self._prefix}{self.label}: {percent:3d}%|{bar}|"
        if self.show_clock and self.total > 0:
            line += f" {format_clock(current)} / {format_clock(self.total)}"
        return line

    def update(self, current: float) -> None:
        """Redraw the bar for *current* progress (in the same unit as *total*)."""
        if self._closed:
            return
        line = self._render(current)
        if line == self._last_line:
            return
        self._last_line = line
        # Trailing spaces clear any remnant of a previously longer line.
        self.stream.write(f"\r{line}   ")
        self.stream.flush()

    def close(self, final_message: str | None = None, complete: bool = True) -> None:
        """
        Finish the bar and move to the next line.

        With *complete* (the default) the bar is snapped to 100% first. Callers
        drive it from frame timestamps or ffmpeg's ``out_time_us``, which stop a
        frame or a rounding error short of the total, so a finished stage would
        otherwise be left reading 99%. Pass ``complete=False`` when the work was
        abandoned part-way and the last real position should stand.
        """
        if self._closed:
            return
        if complete and final_message is None and self._last_line is not None:
            self.update(self.total if self.total > 0 else 1.0)
        self._closed = True
        if self._last_line is None and final_message is None:
            return
        if final_message is not None:
            self.stream.write(f"\r{final_message}")
            # Pad in case the message is shorter than the bar it replaces.
            padding = max(0, len(self._last_line or "") - len(final_message))
            self.stream.write(" " * (padding + 3))
        self.stream.write("\n")
        self.stream.flush()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Don't claim 100% for a stage that blew up part-way through.
        self.close(complete=exc_type is None)
        return False
