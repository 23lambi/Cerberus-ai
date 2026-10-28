"""Plain-language launcher text, independent of the native GUI toolkit."""

PLATFORM_LABELS = {
    "windows-x86_64": "Windows · 64-bit",
    "linux-x86_64": "Linux · 64-bit",
    "macos-arm64": "macOS · Apple Silicon",
    "macos-x86_64": "macOS · Intel",
}


def version_number(value):
    return tuple(int(part) for part in value.lstrip("v").split("-")[0].split(".")[:3])


def install_action(installed, latest):
    if not installed:
        return "Install Cerberus", bool(latest)
    if not latest:
        return "Check for updates", False
    if version_number(latest) > version_number(installed):
        return "Update Cerberus", True
    return "Up to date", False


def ready_message(installed, latest):
    if not installed:
        return "Choose Install Cerberus to get started. The launcher downloads the app for your computer. AI models are set up separately."
    if version_number(latest) > version_number(installed):
        return "An update is ready. Close Cerberus, then choose Update Cerberus. Your chats and settings will be kept."
    return "You're ready. Choose Open Cerberus to start chatting."
