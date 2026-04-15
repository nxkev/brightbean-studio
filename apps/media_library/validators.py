"""File validation for media library uploads."""

import mimetypes

from django.conf import settings

ALLOWED_MIME_TYPES = {
    "image": [
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    ],
    "video": [
        "video/mp4",
        "video/quicktime",
        "video/x-msvideo",
        "video/webm",
    ],
    "document": [
        "application/pdf",
    ],
}

MIME_TO_FILE_TYPE = {}
for file_type, mimes in ALLOWED_MIME_TYPES.items():
    for mime in mimes:
        MIME_TO_FILE_TYPE[mime] = "gif" if mime == "image/gif" else file_type

ALL_ALLOWED_MIMES = set()
for mimes in ALLOWED_MIME_TYPES.values():
    ALL_ALLOWED_MIMES.update(mimes)

ALLOWED_EXTENSIONS = {
    "image": ["jpg", "jpeg", "png", "webp", "gif"],
    "video": ["mp4", "mov", "avi", "webm"],
    "document": ["pdf"],
}

ALL_ALLOWED_EXTENSIONS = set()
for exts in ALLOWED_EXTENSIONS.values():
    ALL_ALLOWED_EXTENSIONS.update(exts)

MAX_FILE_SIZES = {
    "image": getattr(settings, "MEDIA_LIBRARY_MAX_IMAGE_SIZE", 20 * 1024 * 1024),
    "gif": getattr(settings, "MEDIA_LIBRARY_MAX_IMAGE_SIZE", 20 * 1024 * 1024),
    "video": getattr(settings, "MEDIA_LIBRARY_MAX_VIDEO_SIZE", 1024 * 1024 * 1024),
    "document": getattr(settings, "MEDIA_LIBRARY_MAX_IMAGE_SIZE", 20 * 1024 * 1024),
}


def determine_file_type(mime_type):
    """Map a MIME type to our FileType enum value."""
    return MIME_TO_FILE_TYPE.get(mime_type)


# Magic byte signatures for file type verification
_MAGIC_SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",  # WebP starts with RIFF....WEBP, checked further below
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"\x00\x00\x00": "video/mp4",  # ftyp box (checked further below)
    b"\x1aE\xdf\xa3": "video/webm",
    b"%PDF": "application/pdf",
}


def _detect_mime_from_bytes(uploaded_file) -> str | None:
    """Detect MIME type from file magic bytes. Returns None if unrecognized."""
    uploaded_file.seek(0)
    header = uploaded_file.read(32)
    uploaded_file.seek(0)

    if not header:
        return None

    # JPEG
    if header[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    # PNG
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    # GIF
    if header[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    # WebP (RIFF....WEBP)
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    # PDF
    if header[:4] == b"%PDF":
        return "application/pdf"
    # MP4 / QuickTime (ftyp box)
    if header[4:8] == b"ftyp":
        return "video/mp4"
    # AVI (RIFF....AVI )
    if header[:4] == b"RIFF" and header[8:12] == b"AVI ":
        return "video/x-msvideo"
    # WebM / MKV (EBML header)
    if header[:4] == b"\x1aE\xdf\xa3":
        return "video/webm"
    # QuickTime (.mov) — wide/free/mdat atoms without ftyp
    if header[4:8] in (b"moov", b"wide", b"free", b"mdat"):
        return "video/quicktime"

    # Fall back to extension-based detection (but never trust Content-Type header)
    guessed, _ = mimetypes.guess_type(uploaded_file.name or "")
    if guessed and guessed in ALL_ALLOWED_MIMES:
        return guessed

    return None


def validate_file(uploaded_file):
    """Validate an uploaded file. Returns (file_type, errors)."""
    errors = []

    # Detect type from actual file content, not the browser-supplied Content-Type
    detected_mime = _detect_mime_from_bytes(uploaded_file)
    if not detected_mime:
        content_type = uploaded_file.content_type or "unknown"
        errors.append(f"Unsupported file type: {content_type}")
        return None, errors

    file_type = determine_file_type(detected_mime)
    if not file_type:
        errors.append(f"Unsupported file type: {detected_mime}")
        return None, errors

    max_size = MAX_FILE_SIZES.get(file_type, 20 * 1024 * 1024)
    if uploaded_file.size > max_size:
        max_mb = max_size / (1024 * 1024)
        errors.append(f"File too large. Maximum size for {file_type} files is {max_mb:.0f}MB.")

    return file_type, errors


def get_accepted_file_types():
    """Return a comma-separated string of accepted MIME types for HTML file input."""
    return ",".join(sorted(ALL_ALLOWED_MIMES))
