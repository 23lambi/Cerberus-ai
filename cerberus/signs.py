# Reverse step R5: warning signs. Clues that a file may be harmful, found
# without running it.
#
# The most important rule here: Cerberus never says a file is SAFE. No
# check can prove that; new malware gets past every scanner. We only show
# clues, explain them, and say what to do next. A tool that wrongly says
# "safe" is worse than no tool at all.
#
# Each sign is {"level": "warn" or "info", "text": "..."}:
#   warn = a real reason to be careful
#   info = worth knowing, but harmless programs do it too

import asyncio
import io
import math
import re
import shutil
from collections import Counter
from pathlib import Path

import pefile
from elftools.elf.elffile import ELFFile

PACKED_ENTROPY = 7.2  # normal code is about 5.5 to 6.5; packed code is near 8

# Strings that mean "run a command" or "download something". Harmless
# programs rarely contain these as plain text. Downloads only count with
# an address after them: curl's own help text says "Usage: curl [options]",
# and that's not suspicious at all.
COMMANDS = re.compile(
    r"cmd\.exe|powershell|/bin/(ba)?sh -c|(wget|curl)( -\S+)* https?://|"
    r"chmod \+x|/dev/tcp/|nc -e|schtasks|reg add|vssadmin|bcdedit",
    re.IGNORECASE,
)
# Words from ransom notes ("your files are encrypted, pay in bitcoin").
RANSOM = re.compile(r"your files|ransom|bitcoin|decrypt", re.IGNORECASE)
IP_ADDRESS = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
WEB_ADDRESS = re.compile(r"https?://[^\s\"'<>]+")
BASE64_BLOB = re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")  # long hidden data

# File endings that promise a document, picture or media file.
HARMLESS_LOOKING = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".jpg", ".jpeg",
    ".png", ".gif", ".mp3", ".mp4", ".zip",
}

# Ability combinations that are typical for malware. Each one alone is
# normal; together they tell a story.
COMBINATIONS = [
    (
        {"Changes memory or other processes", "Network"},
        "It can talk over the network AND change other programs' memory: "
        "a pattern of programs that inject code into others.",
    ),
    (
        {"Network", "Starts other programs"},
        "It can talk over the network AND start other programs: "
        "it could download something and run it.",
    ),
]


def entropy(data):
    """How random bytes look: 0 (all the same) to 8 (pure noise).

    Each byte has 8 bits. Text and normal code repeat patterns, so they
    need fewer bits per byte to describe (around 4 to 6). Compressed or
    encrypted data has no patterns left, so it's close to 8.
    This is Shannon's entropy: for every byte value with share p of the
    bytes, add p * log2(1 / p).
    """
    if not data:
        return 0.0
    total = len(data)
    return sum(count / total * math.log2(total / count) for count in Counter(data).values())


def code_bytes(data, kind):
    """The bytes of the parts of a program that hold code, and their names."""
    names = []
    parts = []
    try:
        if kind.startswith("ELF"):
            # Segments (not sections): packers often delete the sections.
            # PF_X (= 1) marks a segment the CPU may run as code.
            for segment in ELFFile(io.BytesIO(data)).iter_segments():
                if segment["p_type"] == "PT_LOAD" and segment["p_flags"] & 1:
                    parts.append(segment.data())
        elif kind.startswith("PE"):
            pe = pefile.PE(data=data, fast_load=True)
            for section in pe.sections:
                names.append(section.Name.rstrip(b"\x00").decode(errors="replace"))
                if section.Characteristics & 0x20000000:  # "may run as code"
                    parts.append(section.get_data())
    except Exception:  # a broken file: no code parts to check
        return b"", names
    return b"".join(parts), names


def looks_packed(data, kind):
    """True when the program's code looks random: packed or encrypted."""
    code, _ = code_bytes(data, kind)
    return len(code) > 512 and entropy(code) > PACKED_ENTROPY


def file_signs(name, data, kind, imports_total):
    signs = []

    # 1. Packed: the code looks random, because it's compressed or
    #    encrypted and only unpacks itself while running.
    code, section_names = code_bytes(data, kind)
    randomness = entropy(code)
    if len(code) > 512 and randomness > PACKED_ENTROPY:
        signs.append({
            "level": "warn",
            "text": f"The code looks random (entropy {randomness:.1f} of 8): it's "
            "probably packed or encrypted, so its real code is hidden.",
        })
    if any(n.startswith("UPX") for n in section_names) or b"UPX!" in data[:4096]:
        signs.append({"level": "warn", "text": "Packed with UPX, a well-known packer."})
    if kind.startswith("PE") and imports_total <= 5:
        signs.append({
            "level": "warn",
            "text": f"Only {imports_total} imports: Windows programs normally have dozens. "
            "Packed programs load the rest while running.",
        })

    # 2. A name that lies: "invoice.pdf.exe", or a program called "photo.jpg".
    #    The U+202E character flips the text direction to hide the real ending.
    if "‮" in name:
        signs.append({"level": "warn", "text": "The file name hides its real ending with a direction-flip character."})
    endings = [suffix.lower() for suffix in Path(name).suffixes]
    is_program = kind.startswith(("ELF", "PE", "Mach-O"))
    if is_program and any(ending in HARMLESS_LOOKING for ending in endings):
        signs.append({
            "level": "warn",
            "text": f'The name "{name}" looks like a document or picture, but it\'s a program.',
        })
    return signs


def first_matches(pattern, texts, limit=3):
    """The first few different matches of a pattern in the strings."""
    found = []
    for text in texts:
        for match in pattern.findall(text):
            if match not in found:
                found.append(match)
    return found[:limit]


def string_signs(strings):
    signs = []
    texts = [item["text"] for item in strings]

    commands = [text for text in texts if COMMANDS.search(text)][:3]
    if commands:
        signs.append({"level": "warn", "text": "Contains commands: " + " | ".join(commands)})
    ransom = [text for text in texts if RANSOM.search(text)][:3]
    if ransom:
        signs.append({"level": "warn", "text": "Words like in a ransom note: " + " | ".join(ransom)})

    # IP addresses: every part must be 0-255 (so "1.2.300.4" is a version
    # number, not an address), and we skip addresses that mean "nobody".
    ips = [
        ip
        for ip in first_matches(IP_ADDRESS, texts, limit=20)
        if all(int(part) <= 255 for part in ip.split("."))
        and ip not in ("0.0.0.0", "127.0.0.1", "255.255.255.255")
    ]
    if ips:
        signs.append({"level": "info", "text": "IP addresses: " + ", ".join(ips[:3])})

    urls = first_matches(WEB_ADDRESS, texts)
    if urls:
        signs.append({"level": "info", "text": "Web addresses: " + ", ".join(urls)})
    if any(BASE64_BLOB.search(text) for text in texts):
        signs.append({"level": "info", "text": "Long blocks of base64 text: data that may be hidden on purpose."})
    return signs


# Debugger checks that compilers do NOT add by themselves. (Almost every
# Windows program imports IsDebuggerPresent, so that one says nothing.)
RARE_DEBUGGER_CHECKS = {"CheckRemoteDebuggerPresent", "NtQueryInformationProcess", "ptrace"}


def ability_signs(capabilities):
    have = {group["what"] for group in capabilities}
    # "<=" on sets means "is part of": every ability of the pattern is there.
    signs = [{"level": "warn", "text": text} for needed, text in COMBINATIONS if needed <= have]

    functions = {f for group in capabilities for f in group["functions"]}
    if functions & RARE_DEBUGGER_CHECKS and "Loads code while running" in have:
        signs.append({
            "level": "warn",
            "text": "It checks for a debugger in an unusual way AND loads code while "
            "running: a pattern of programs that hide what they do from analysts.",
        })
    return signs


def find(name, data, kind, strings, capabilities, imports_total):
    """All warning signs for a file."""
    return (
        file_signs(name, data, kind, imports_total)
        + ability_signs(capabilities)
        + string_signs(strings)
    )


# ---------- ClamAV, a free virus scanner (optional) ----------


async def clamav_scan(data):
    """Scan with ClamAV if it's installed. Returns {"available": bool, ...}.

    ClamAV compares the file with a big list of known malware patterns.
    It's a separate program, so we start it and give it the file through
    its input ("-" = read from stdin); the file never touches the disk.
    """
    if shutil.which("clamscan") is None:
        return {"available": False}
    process = await asyncio.create_subprocess_exec(
        "clamscan", "--no-summary", "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        # ClamAV loads its whole pattern list first, which takes a while.
        output, _ = await asyncio.wait_for(process.communicate(data), timeout=120)
    except asyncio.TimeoutError:
        process.kill()
        return {"available": True, "error": "ClamAV took too long."}

    # Exit code 0 = nothing found, 1 = found something, 2 = an error.
    text = output.decode(errors="replace").strip()
    if process.returncode == 1:
        # The output looks like: "stdin: Eicar-Test-Signature FOUND"
        names = [line.split(":", 1)[-1].replace("FOUND", "").strip() for line in text.splitlines() if "FOUND" in line]
        return {"available": True, "found": names}
    if process.returncode == 0:
        return {"available": True, "found": []}
    return {"available": True, "error": text or "ClamAV failed."}
