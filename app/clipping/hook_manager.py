"""
clipping.hook_manager — Custom hook clip resolution for ``--hook-source``.
"""

import os
import shutil


def _download_http(source: str, local_path: str) -> str | None:
    """Download a hook clip from a Google Drive link, or any direct URL."""
    import gdown

    print(f"📥 Downloading the custom hook from: {source}")
    try:
        # Google Drive share links embed the file ID after /d/.
        file_id = source.split("/d/")[1].split("/")[0] if "/d/" in source else source
        gdown.download(f"https://drive.google.com/uc?id={file_id}", local_path, quiet=False)
        if os.path.exists(local_path):
            print(f"   ✅ Custom hook downloaded to {local_path}")
            return local_path

        # Not a Drive ID after all — try it as a direct media link.
        import requests

        response = requests.get(source, stream=True, timeout=60)
        if response.status_code != 200:
            return None
        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        print(f"   ✅ Custom hook downloaded to {local_path}")
        return local_path
    except Exception as e:
        print(f"⚠️ Failed to download the custom hook: {e}")
        return None


def download_custom_hook(cfg) -> str | None:
    """
    Resolve the ``--hook-source`` argument to a local MP4 file.

    Returns the absolute path to the local file, or None if it is unset or
    could not be resolved.
    """
    source = cfg.hook_source
    if not source:
        return None

    cache_dir = os.path.join(cfg.outputs_dir, "hooks_cache")
    os.makedirs(cache_dir, exist_ok=True)
    local_path = os.path.join(cache_dir, "custom_hook_override.mp4")

    if source.startswith("http"):
        return _download_http(source, local_path)

    if not os.path.exists(source):
        print(f"⚠️ Local hook source not found: {source}")
        return None

    print(f"📥 Using the local hook file: {source}")
    try:
        shutil.copy(source, local_path)
        return local_path
    except shutil.SameFileError:
        return source
    except Exception as e:
        print(f"⚠️ Failed to copy the local hook file: {e}")
        return source
