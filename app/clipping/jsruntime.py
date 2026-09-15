"""
clipping.jsruntime — Make sure yt-dlp has a JavaScript runtime.

yt-dlp needs a JS runtime to solve YouTube's signature and "n" challenges. When
it cannot, it does not fail loudly: it silently drops every format it could not
decrypt and the download dies with "Requested format is not available", which
says nothing about JavaScript. Colab and Kaggle ship neither Deno (the only
runtime yt-dlp enables by default) nor a new enough Node — yt-dlp wants Node 22+
and those images are usually older — so the runtime has to be installed.

Deno's own install script needs ``unzip`` or ``7z``, which is not guaranteed on
those images, so the binary is fetched and unpacked with the standard library
instead. That has no external dependencies at all.
"""

import os
import shutil
import stat
import sys
import urllib.request
import zipfile

from . import ytdl

DENO_RELEASE_URL = (
    "https://github.com/denoland/deno/releases/latest/download/deno-{target}.zip"
)

# Deno's release asset names, keyed by (platform, machine).
_DENO_TARGETS = {
    ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("linux", "arm64"): "aarch64-unknown-linux-gnu",
    ("darwin", "x86_64"): "x86_64-apple-darwin",
    ("darwin", "arm64"): "aarch64-apple-darwin",
    ("win32", "amd64"): "x86_64-pc-windows-msvc",
    ("win32", "x86_64"): "x86_64-pc-windows-msvc",
}


def _deno_target() -> str | None:
    import platform

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        machine = "x86_64" if sys.platform != "win32" else "amd64"
    return _DENO_TARGETS.get((sys.platform, machine))


def _install_dir() -> str:
    """A directory on PATH that we can write to."""
    for candidate in ("/usr/local/bin", os.path.expanduser("~/.local/bin")):
        try:
            os.makedirs(candidate, exist_ok=True)
            if os.access(candidate, os.W_OK):
                return candidate
        except OSError:
            continue
    return os.path.expanduser("~")


def install_deno(install_dir: str | None = None) -> str | None:
    """Download the Deno binary into *install_dir*; return its path, or None."""
    target = _deno_target()
    if not target:
        import platform

        print(f"⚠️ No Deno build for {sys.platform}/{platform.machine()}.")
        return None

    install_dir = install_dir or _install_dir()
    exe = "deno.exe" if sys.platform == "win32" else "deno"
    dest = os.path.join(install_dir, exe)

    url = DENO_RELEASE_URL.format(target=target)
    tmp_zip = os.path.join(install_dir, ".deno-download.zip")

    print(f"⬇️  Installing Deno (JS runtime for yt-dlp) into {install_dir}...", flush=True)
    try:
        urllib.request.urlretrieve(url, tmp_zip)
        with zipfile.ZipFile(tmp_zip) as archive:
            with archive.open(exe) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    except Exception as e:
        print(f"⚠️ Could not install Deno: {e}")
        return None
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)

    os.chmod(dest, os.stat(dest).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # yt-dlp finds runtimes on PATH, so make sure this directory is on it for
    # the current process too (a notebook keeps running after the setup cell).
    if install_dir not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = install_dir + os.pathsep + os.environ.get("PATH", "")

    return dest


def ensure_js_runtime(install_dir: str | None = None) -> str | None:
    """
    Return the name of a usable JS runtime, installing Deno if there is none.

    Safe to call repeatedly: an already-present runtime short-circuits it.
    """
    existing = ytdl.available_js_runtime()
    if existing:
        print(f"✅ JavaScript runtime available for yt-dlp: {existing}")
        return existing

    if not install_deno(install_dir):
        return None

    ytdl.reset_runtime_cache()
    found = ytdl.available_js_runtime()
    if found:
        print(f"✅ JavaScript runtime installed and detected: {found}")
    else:
        print(
            "⚠️ Deno was downloaded but yt-dlp still cannot see a runtime. "
            "Check that the install directory is on PATH."
        )
    return found


if __name__ == "__main__":
    sys.exit(0 if ensure_js_runtime() else 1)
