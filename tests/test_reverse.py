# Tests for the Reverse feature. We build tiny fake program headers by
# hand, byte by byte, so we know exactly what the answer must be.

import json
import sys
from pathlib import Path

import pytest

from cerberus.analysis import reverse


def fake_elf(machine=0x3E):
    header = bytearray(64)  # 64 zero bytes we can change
    header[0:4] = b"\x7fELF"  # the magic bytes
    header[4] = 2  # 64-bit
    header[5] = 1  # little endian
    header[18:20] = machine.to_bytes(2, "little")  # the CPU
    return bytes(header)


def fake_pe(machine=0x8664):
    data = bytearray(0x80)
    data[0:2] = b"MZ"
    data[0x3C:0x40] = (0x40).to_bytes(4, "little")  # where the PE header is
    data[0x40:0x44] = b"PE\x00\x00"
    data[0x44:0x46] = machine.to_bytes(2, "little")
    return bytes(data)


def test_elf_program():
    facts = reverse.analyze("crackme", fake_elf())
    assert facts["type"] == "ELF program (Linux)"
    assert facts["details"] == "64-bit, x86-64"


def test_windows_program():
    assert reverse.analyze("game.exe", fake_pe())["details"] == "x86-64"


def test_broken_header_does_not_crash():
    # Starts like a Windows program, but the rest is missing.
    facts = reverse.analyze("broken.exe", b"MZ" + b"\x00" * 10)
    assert facts["type"].startswith("PE")
    assert facts["details"] is None


def test_scripts_are_text():
    facts = reverse.analyze("run.sh", "#!/bin/sh\necho héllo\n".encode())
    assert facts["type"] == "Text (a script or source code)"


def test_strings_and_where_they_are():
    data = b"\x00\x01Enter password:\x00\xffok\x00Correct!\x00"
    strings = reverse.analyze("x", data)["strings"]
    # "ok" is too short to count; the offsets say where each string starts.
    assert strings == [
        {"offset": 2, "text": "Enter password:"},
        {"offset": 22, "text": "Correct!"},
    ]


def test_hash_is_the_files_fingerprint():
    # The well-known sha256 of "abc", from the SHA-2 standard.
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert reverse.analyze("x", b"abc")["sha256"] == expected


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs a Linux program")
def test_a_real_program():
    # The Python program running these tests is a real ELF file.
    with open(sys.executable, "rb") as file:
        facts = reverse.analyze("python", file.read())
    assert facts["type"] == "ELF program (Linux)"
    assert facts["strings_total"] > 0


def test_upload(client):
    response = client.post("/reverse?name=crackme", content=fake_elf())
    assert response.json()["details"] == "64-bit, x86-64"


def test_empty_upload(client):
    assert client.post("/reverse?name=empty", content=b"").status_code == 400


# ---------- R2: imports ----------


def test_capabilities_understand_renamed_functions():
    found = reverse.capabilities(
        ["__isoc99_scanf", "strcmp", "CreateProcessW", "IsDebuggerPresent", "socket", "bindtextdomain"]
    )
    # bindtextdomain starts with "bind" but has nothing to do with networks.
    assert found == [
        {"what": "Network", "functions": ["socket"]},
        {"what": "Starts other programs", "functions": ["CreateProcessW"]},
        {"what": "Reads input", "functions": ["__isoc99_scanf"]},
        {"what": "Compares text", "functions": ["strcmp"]},
        {"what": "Checks for a debugger", "functions": ["IsDebuggerPresent"]},
    ]


def test_fake_programs_have_no_imports():
    # Our hand-made headers have no import tables; that must not crash.
    assert reverse.analyze("crackme", fake_elf())["imports"] == []
    assert reverse.analyze("game.exe", fake_pe())["imports"] == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs a Linux program")
def test_imports_of_a_real_linux_program():
    with open(sys.executable, "rb") as file:
        facts = reverse.analyze("python", file.read())
    assert any("libc" in library for library in facts["libraries"])
    assert facts["imports_total"] > 0


# pip comes with small Windows programs (launchers). A real .exe to test with!
WINDOWS_EXE = Path(pytest.__file__).parents[1] / "pip/_vendor/distlib/t64.exe"


@pytest.mark.skipif(not WINDOWS_EXE.exists(), reason="no Windows program to test with")
def test_imports_of_a_real_windows_program():
    facts = reverse.analyze("t64.exe", WINDOWS_EXE.read_bytes())
    assert "KERNEL32.dll" in facts["libraries"]
    # It's a launcher: it starts other programs with CreateProcessW.
    assert "Starts other programs" in [group["what"] for group in facts["capabilities"]]


# ---------- R4: the fact sheet and asking the model ----------


def crackme_facts():
    # The facts of a small password program, the way /reverse returns them.
    data = fake_elf() + b"\x00Enter password:\x00Correct!\x00Wrong!\x00.text\x00GLIBC_2.34\x00"
    return reverse.analyze("crackme", data)


def test_fact_sheet_keeps_useful_strings_only():
    sheet = reverse.fact_sheet(crackme_facts())
    assert "Type: ELF program (Linux), 64-bit, x86-64" in sheet
    assert "Enter password:" in sheet and "Correct!" in sheet
    # Section names and version tags tell a human nothing.
    assert ".text" not in sheet and "GLIBC_2.34" not in sheet


def test_fact_sheet_stays_small():
    facts = reverse.analyze("big", b"\x00".join(b"some readable text %d" % i for i in range(5000)))
    assert len(reverse.fact_sheet(facts)) < 4000


def test_asking_about_a_file(client, fake):
    body = {
        "model": "small:3b",
        "facts": crackme_facts(),
        "messages": [{"role": "user", "content": "Explain this program"}],
    }
    response = client.post("/reverse/chat", json=body)

    # The answer is NDJSON, like /chat: one JSON object per line.
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["content", "stats"]
    system = fake.calls[-1]["messages"][0]["content"]
    assert "reverse engineering" in system  # the skill from prompts.py
    assert "Enter password:" in system  # the facts


# ---------- R3: disassembly ----------
# tests/fixtures has two small crackmes, compiled and stripped (no function
# names), with their C source next to them.

FILES = Path(__file__).parent / "fixtures"


def test_main_is_found_in_a_stripped_program():
    functions = reverse.analyze("crackme", (FILES / "crackme").read_bytes())["disassembly"]
    main = functions[0]
    assert main["name"] == "main (found from the entry point)"

    notes = [line["note"] for line in main["lines"]]
    assert '"Enter password: "' in notes
    assert '"c3rb3rus_r0cks"' in notes
    assert "strcmp" in notes
    assert "jump if not equal" in notes


def test_functions_called_by_main_show_their_letters():
    functions = reverse.analyze("crackme2", (FILES / "crackme2").read_bytes())["disassembly"]
    assert len(functions) == 2  # main, and the password check it calls
    check = functions[1]
    assert check["name"].endswith("(called by main)")
    letters = [line["note"] for line in check["lines"] if line["text"].startswith("cmp al")]
    assert letters == ["'d'", "'o'", "'g'", "'!'"]


def test_no_disassembly_for_files_we_cant_read():
    assert reverse.analyze("crackme", fake_elf())["disassembly"] is None
    assert reverse.analyze("game.exe", fake_pe())["disassembly"] is None


def test_fact_sheet_has_the_code():
    sheet = reverse.fact_sheet(reverse.analyze("crackme", (FILES / "crackme").read_bytes()))
    assert "Disassembly" in sheet
    assert "; strcmp" in sheet
