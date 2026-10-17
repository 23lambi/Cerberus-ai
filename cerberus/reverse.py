# The Reverse feature: take a program apart and explain it, WITHOUT ever
# running it. Cerberus only reads the file's bytes, so even a harmful
# program can't do anything here.
#
# Step R1: what kind of file it is, its fingerprint (hash), and the
# readable text inside it (strings).
# Step R2: which functions it uses from libraries (imports), and what
# that says about what it can do.
# Step R3: the program's code as assembly (see disasm.py).
# Step R4: a short "fact sheet" for the model, so it can explain the file.
# Step R5: warning signs that a file may be harmful (see signs.py).

import hashlib
import io
import re
import struct
from pathlib import Path

import pefile  # reads Windows programs (PE)
from elftools.elf.elffile import ELFFile  # reads Linux programs (ELF)

from cerberus import disasm, signs

MIN_STRING = 6  # shorter runs of letters are mostly noise
MAX_STRINGS = 300  # the page doesn't need more than this
MAX_IMPORTS = 500
SHEET_IMPORTS = 200  # imports on the fact sheet
SHEET_STRINGS_CHARS = 3000  # about 750 tokens of strings on the fact sheet
SHEET_CODE_CHARS = 7000  # about 2000 tokens of assembly on the fact sheet

# Strings that say nothing to a human: section names like ".text", and
# version tags like "GLIBC_2.34" or "_ITM_registerTMCloneTable".
NOISE = re.compile(r"^(\.|_|GLIBC|GLIBCXX|GCC_|CXXABI)")

# The first bytes of a file say what kind of file it is ("magic bytes").
MAGIC = [
    (b"\x7fELF", "ELF program (Linux)"),
    (b"MZ", "PE program (Windows .exe / .dll)"),
    (b"\xcf\xfa\xed\xfe", "Mach-O program (macOS)"),
    (b"\xca\xfe\xba\xbe", "Java class or macOS universal program"),
    (b"PK\x03\x04", "ZIP archive (also .jar, .apk, .docx)"),
    (b"%PDF", "PDF document"),
    (b"\x89PNG", "PNG image"),
]

# Which CPU a program is made for. The numbers come from the ELF and PE
# specifications (the official descriptions of these file formats).
ELF_MACHINES = {0x03: "x86 (32-bit)", 0x3E: "x86-64", 0x28: "ARM (32-bit)", 0xB7: "ARM64", 0xF3: "RISC-V"}
PE_MACHINES = {0x14C: "x86 (32-bit)", 0x8664: "x86-64", 0xAA64: "ARM64"}

# rb"..." is a regex for bytes. [\x20-\x7e] = one readable character
# (space to ~), and {6,} = at least 6 of them in a row.
STRING_PATTERN = re.compile(rb"[\x20-\x7e]{%d,}" % MIN_STRING)


def is_text(data):
    # Text has no zero bytes and is valid UTF-8. We only look at the start;
    # the cut there may split one letter, so one broken letter is allowed.
    sample = data[:8192]
    if b"\x00" in sample:
        return False
    return sample.decode("utf-8", errors="replace").count("�") <= 1


def file_type(data):
    for magic, kind in MAGIC:
        if data.startswith(magic):
            return kind
    if is_text(data):
        return "Text (a script or source code)"
    return "Unknown binary data"


def elf_details(data):
    # The ELF header: byte 4 says 32 or 64 bit, byte 5 the byte order,
    # and bytes 18-19 the CPU ("e_machine").
    if len(data) < 20:
        return None
    bits = {1: "32-bit", 2: "64-bit"}.get(data[4], "unknown bits")
    order = "<" if data[5] == 1 else ">"  # 1 = little endian, 2 = big endian
    # struct.unpack_from reads a number from raw bytes. "H" = 2 bytes.
    (machine,) = struct.unpack_from(order + "H", data, 18)
    return f"{bits}, {ELF_MACHINES.get(machine, hex(machine))}"


def pe_details(data):
    # A Windows program starts with an old DOS header ("MZ"). At byte 0x3C
    # it says where the real PE header is. That one starts with "PE\0\0",
    # and the next 2 bytes are the CPU.
    if len(data) < 0x40:
        return None
    (start,) = struct.unpack_from("<I", data, 0x3C)  # "I" = 4 bytes
    if data[start : start + 4] != b"PE\x00\x00" or start + 6 > len(data):
        return None  # a broken or fake header: say nothing rather than guess
    (machine,) = struct.unpack_from("<H", data, start + 4)
    return PE_MACHINES.get(machine, hex(machine))


# What a program can do, recognised by the functions it imports.
# A name ending in * is a family: "exec*" means execve, execl, execvp...
CAPABILITIES = {
    "Network": [
        "socket", "connect", "bind", "listen", "accept", "send", "sendto", "recv",
        "recvfrom", "getaddrinfo", "gethostbyname", "WSAStartup", "Internet*",
        "WinHttp*", "URLDownloadToFile", "curl_*",
    ],
    "Starts other programs": [
        "system", "popen", "fork", "exec*", "posix_spawn*", "CreateProcess",
        "ShellExecute", "WinExec",
    ],
    "Reads input": ["scanf", "fgets", "gets", "getline", "getchar", "ReadConsole"],
    "Compares text": ["strcmp", "strncmp", "strcasecmp", "memcmp", "lstrcmp", "CompareString"],
    "Works with files": [
        "fopen", "open", "openat", "unlink", "remove", "rename", "mkdir", "opendir",
        "CreateFile", "DeleteFile", "CopyFile", "MoveFile", "FindFirstFile",
    ],
    "Changes memory or other processes": [
        "mprotect", "VirtualAlloc", "VirtualProtect", "WriteProcessMemory",
        "ReadProcessMemory", "CreateRemoteThread", "OpenProcess",
    ],
    "Checks for a debugger": [
        "ptrace", "IsDebuggerPresent", "CheckRemoteDebuggerPresent",
        "NtQueryInformationProcess",
    ],
    "Loads code while running": ["dlopen", "dlsym", "LoadLibrary", "GetProcAddress"],
    "Encryption": ["EVP_*", "AES_*", "Crypt*", "BCrypt*"],
    "Windows registry": ["RegOpenKey", "RegSetValue", "RegCreateKey", "RegQueryValue"],
}


def clean_name(name):
    # The same function can have different names in a program:
    #   Linux:   "__isoc99_scanf" is scanf, "__printf_chk" is printf
    #   Windows: CreateProcessA / CreateProcessW are the same function for
    #            old text (A) and Unicode text (W); "...Ex" is a newer version
    name = re.sub(r"^_+(isoc\d+_)?", "", name)
    name = re.sub(r"_chk$", "", name)
    return re.sub(r"(Ex)?[AW]?$", "", name)


def capabilities(functions):
    """Groups like {"what": "Network", "functions": ["connect", "socket"]}."""
    found = []
    for what, names in CAPABILITIES.items():
        hits = []
        for function in functions:
            clean = clean_name(function)
            for name in names:
                is_family = name.endswith("*")
                if clean == name or (is_family and clean.startswith(name[:-1])):
                    hits.append(function)
                    break
        if hits:
            found.append({"what": what, "functions": hits})
    return found


def elf_imports(data):
    # pyelftools reads the structure of an ELF file. Two parts matter:
    #   .dynamic  the libraries the program needs (DT_NEEDED), like libc.so.6
    #   .dynsym   its symbols. The "undefined" ones (SHN_UNDEF) are not in
    #             the program itself but in those libraries: its imports.
    try:
        elf = ELFFile(io.BytesIO(data))  # BytesIO: the bytes act like a file
        dynamic = elf.get_section_by_name(".dynamic")
        symbols = elf.get_section_by_name(".dynsym")
        libraries = []
        if dynamic:
            libraries = [tag.needed for tag in dynamic.iter_tags() if tag.entry.d_tag == "DT_NEEDED"]
        functions = []
        if symbols:
            functions = [s.name for s in symbols.iter_symbols() if s.name and s["st_shndx"] == "SHN_UNDEF"]
    except Exception:
        # A broken or fake file can make the library fail in many different
        # ways. Then we simply report no imports instead of crashing.
        return [], []
    return libraries, sorted(set(functions))


def pe_imports(data):
    # pefile reads the structure of a Windows program. Its import table
    # lists, for each DLL (library), the functions used from it.
    try:
        pe = pefile.PE(data=data, fast_load=True)  # fast_load: skip the rest
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
    except Exception:  # broken or fake file, see elf_imports
        return [], []

    libraries = []
    functions = []
    # getattr(..., []): the import table is missing when there are no imports.
    for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        library = entry.dll.decode(errors="replace")
        libraries.append(library)
        for item in entry.imports:
            if item.name:
                functions.append(item.name.decode(errors="replace"))
            else:
                # Imported by number ("ordinal") instead of by name.
                functions.append(f"{library}#{item.ordinal}")
    return libraries, sorted(set(functions))


def find_strings(data):
    # Like the Linux tool "strings": every run of readable characters, with
    # its offset (how many bytes from the start of the file it is).
    return [
        {"offset": match.start(), "text": match.group().decode("ascii")}
        for match in STRING_PATTERN.finditer(data)
    ]


def analyze(name, data):
    kind = file_type(data)
    details = None
    libraries, functions = [], []
    code = None
    if kind.startswith("ELF"):
        details = elf_details(data)
        libraries, functions = elf_imports(data)
        # Random-looking (packed) code still "disassembles", but into
        # nonsense instructions, and a model would happily explain the
        # nonsense. So packed programs get no disassembly.
        if not signs.looks_packed(data, kind):
            code = disasm.disassemble(data)
    elif kind.startswith("PE"):
        details = pe_details(data)
        libraries, functions = pe_imports(data)

    strings = find_strings(data)
    found = capabilities(functions)
    return {
        "name": Path(name).name,
        "size": len(data),
        "type": kind,
        "details": details,
        # The sha256 hash is the file's fingerprint: change one byte and it's
        # completely different. Security sites use it to look files up.
        "sha256": hashlib.sha256(data).hexdigest(),
        "strings": strings[:MAX_STRINGS],
        "strings_total": len(strings),
        "libraries": libraries,
        "imports": functions[:MAX_IMPORTS],
        "imports_total": len(functions),
        "capabilities": found,
        "disassembly": code,  # None for files we can't disassemble (yet)
        # All strings are checked, not only the first MAX_STRINGS we show.
        "signs": signs.find(Path(name).name, data, kind, strings, found, len(functions)),
    }


def fact_sheet(facts):
    """The facts as a short text for the model, a few thousand characters.

    The model's context window is small (8192 tokens on your setup), so we
    choose: the summary, the abilities, the imports, and the most useful
    strings, until the budget is used up.
    """
    kind = facts["type"]
    if facts.get("details"):
        kind += ", " + facts["details"]
    lines = [f"File: {facts['name']}", f"Type: {kind}", f"Size: {facts['size']} bytes"]

    if facts.get("signs"):
        lines.append("Warning signs Cerberus found:")
        lines += [f"- [{sign['level']}] {sign['text']}" for sign in facts["signs"]]
    else:
        lines.append("Warning signs Cerberus found: none")
    if facts.get("libraries"):
        lines.append("Libraries: " + ", ".join(facts["libraries"]))
    for group in facts.get("capabilities", []):
        lines.append(f"Can: {group['what']} ({', '.join(group['functions'])})")
    if facts.get("imports"):
        shown = facts["imports"][:SHEET_IMPORTS]
        lines.append(f"Imports ({facts['imports_total']} in total): " + ", ".join(shown))

    # Strings: skip the noise and the ones that are just import names.
    imports = set(facts.get("imports", []))
    picked = []
    used = 0
    for item in facts.get("strings", []):
        text = item["text"]
        if text in imports or NOISE.match(text):
            continue
        if used + len(text) > SHEET_STRINGS_CHARS:
            break
        picked.append(text)
        used += len(text)
    if picked:
        lines.append("Readable strings in the file, in order:\n" + "\n".join(picked))

    # The assembly, with Cerberus's notes after the ";". Cut at the budget.
    if facts.get("disassembly"):
        code = disasm.as_text(facts["disassembly"])
        if len(code) > SHEET_CODE_CHARS:
            code = code[:SHEET_CODE_CHARS] + "\n... (the rest didn't fit)"
        lines.append("Disassembly (x86-64, Intel syntax; notes after ';'):\n" + code)
    elif kind.startswith(("ELF", "PE")):
        # Say it plainly. When something is just missing, small models
        # don't notice and invent the code instead.
        lines.append(
            "Disassembly: none. Cerberus could not read the code (it may be "
            "packed, or it's not a Linux x86-64 program). Do not guess what the code does."
        )

    return "\n".join(lines)
