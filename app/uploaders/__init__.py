"""
app.uploaders — Publishing back-ends for rendered clips.

Each platform keeps its own module, and nothing is imported eagerly here so
that using one uploader does not require the other's dependencies:

    from app.uploaders.youtube import upload_manifest_to_youtube
    from app.uploaders.instagram import upload_manifest_to_instagram

Both read the same ``render_manifest.json`` produced by the clipping pipeline
and write their results back as extra per-row fields (see ``manifest.py``).
"""
