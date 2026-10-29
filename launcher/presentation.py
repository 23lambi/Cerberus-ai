"""Plain-language launcher text, independent of the native GUI toolkit."""

PLATFORM_LABELS = {
    "windows-x86_64": "Windows · 64-bit",
    "linux-x86_64": "Linux · 64-bit",
    "macos-arm64": "macOS · Apple Silicon",
    "macos-x86_64": "macOS · Intel",
}


def version_number(value):
    return tuple(int(part) for part in value.lstrip("v").split("-")[0].split(".")[:3])


def is_newer(latest, installed):
    """True when latest is a newer release than installed."""
    return version_number(latest) > version_number(installed)


def size_label(size):
    return f"{size / 1024**2:.0f} MB" if size >= 1024**2 else f"{max(size, 0) / 1024:.0f} KB"


def progress_label(done, total):
    if not total:
        return "Preparing…"
    return f"{done / total:.0%} · {size_label(done)} of {size_label(total)}"
