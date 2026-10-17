# Tests for the warning signs (R5). Harmless programs must stay quiet, and
# a file that looks harmful must be noticed. Both matter: a tool that
# warns about everything is as useless as one that warns about nothing.

import io
import os
import random
import sys
from pathlib import Path

import pytest
from elftools.elf.elffile import ELFFile

from cerberus import reverse, signs

FILES = Path(__file__).parent / "files"


def warnings_for(name, data):
    facts = reverse.analyze(name, data)
    return [sign["text"] for sign in facts["signs"] if sign["level"] == "warn"]


def looks_harmful():
    """Our crackme, made to look like malware.

    Its code is replaced by random bytes (that's how packed code looks),
    and some typical malware strings are added at the end.
    The random bytes come from random.Random(1): the same "random" bytes
    on every run, so the test always checks the same file. A test whose
    result changes from run to run ("flaky") is worse than no test.
    """
    noise = random.Random(1)
    data = bytearray((FILES / "crackme").read_bytes())
    for segment in ELFFile(io.BytesIO(bytes(data))).iter_segments():
        if segment["p_type"] == "PT_LOAD" and segment["p_flags"] & 1:
            start = segment["p_offset"]
            data[start : start + segment["p_filesz"]] = noise.randbytes(segment["p_filesz"])
    return bytes(data) + (
        b"\x00powershell -nop -w hidden\x00YOUR FILES ARE ENCRYPTED, pay in bitcoin"
        b"\x00connect to 45.33.32.156\x00"
    )


def test_entropy():
    assert signs.entropy(bytes(1000)) == 0.0  # all the same: no surprise at all
    assert signs.entropy(os.urandom(100_000)) > 7.9  # pure noise: almost 8
    assert 3 < signs.entropy(b"hello world, this is plain text") < 5


def test_a_harmless_program_has_no_warnings():
    assert warnings_for("crackme", (FILES / "crackme").read_bytes()) == []


def test_a_harmful_looking_file_is_noticed():
    found = " ".join(warnings_for("invoice.pdf.exe", looks_harmful()))
    assert "probably packed" in found
    assert "looks like a document" in found
    assert "powershell" in found
    assert "ransom" in found


def test_no_false_alarms_from_normal_text():
    harmless = [
        {"text": "Usage: curl [options...] <url>"},  # curl's own help text
        {"text": "version 1.2.300.4"},  # a version number, not an IP address
    ]
    assert signs.string_signs(harmless) == []


WINDOWS_EXE = Path(pytest.__file__).parents[1] / "pip/_vendor/distlib/t64.exe"


@pytest.mark.skipif(not WINDOWS_EXE.exists(), reason="no Windows program to test with")
def test_normal_windows_imports_are_not_a_warning():
    # Almost every Windows program imports IsDebuggerPresent and
    # LoadLibrary, because the compiler adds them. No warning for that.
    assert warnings_for("t64.exe", WINDOWS_EXE.read_bytes()) == []


def test_packed_code_gets_no_disassembly():
    assert reverse.analyze("invoice.pdf.exe", looks_harmful())["disassembly"] is None


def test_fact_sheet_mentions_the_signs():
    sheet = reverse.fact_sheet(reverse.analyze("invoice.pdf.exe", looks_harmful()))
    assert "Warning signs Cerberus found:" in sheet
    assert "probably packed" in sheet
    # Its code is unreadable, and the sheet must say so (or models invent it).
    assert "Disassembly: none" in sheet


# ---------- ClamAV ----------


def test_clamav_not_installed(client, monkeypatch):
    monkeypatch.setattr(signs.shutil, "which", lambda name: None)
    assert client.post("/reverse/clamav", content=b"abc").json() == {"available": False}


@pytest.mark.skipif(sys.platform == "win32", reason="the fake scanner is a shell script")
def test_clamav_finds_something(client, monkeypatch, tmp_path):
    # A fake "clamscan" that always finds the EICAR test signature. We put
    # its folder first in PATH, so it's found instead of a real one.
    fake = tmp_path / "clamscan"
    fake.write_text('#!/bin/sh\ncat > /dev/null\necho "stdin: Eicar-Test-Signature FOUND"\nexit 1\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])

    result = client.post("/reverse/clamav", content=b"abc").json()
    assert result == {"available": True, "found": ["Eicar-Test-Signature"]}
