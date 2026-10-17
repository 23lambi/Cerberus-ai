# Reverse step R3: turn a program's machine code into assembly, with notes
# in plain words, so a person (or a model) can follow its logic.
#
# Machine code is just bytes, like 48 8d 3d 6f 0e 00 00. The capstone
# library turns them into assembly: lea rdi, [rip + 0xe6f]. That still
# says little, so we add notes: which string that address points to, which
# imported function a call goes to, and what a jump means.
#
# For now: Linux programs (ELF) for x86-64, the CPU in most PCs and CTFs.

import io

from capstone import CS_ARCH_X86, CS_MODE_64, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_REG_RIP
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection

MAX_INSTRUCTIONS = 300  # about what fits in the model's context window
MAX_BYTES = 4096

# Functions that never come back. After a call to one of them, the
# function we are reading is over.
NO_RETURN = {"exit", "_exit", "abort", "__stack_chk_fail", "__assert_fail"}

# Conditional jumps in plain words. They come after a cmp or test.
JUMP_WORDS = {
    "je": "jump if equal", "jz": "jump if zero",
    "jne": "jump if not equal", "jnz": "jump if not zero",
    "jg": "jump if greater", "jge": "jump if greater or equal",
    "jl": "jump if less", "jle": "jump if less or equal",
    "ja": "jump if above", "jae": "jump if above or equal",
    "jb": "jump if below", "jbe": "jump if below or equal",
    "js": "jump if negative", "jns": "jump if not negative",
}


class Program:
    """An ELF program we can read by address, like the CPU sees it."""

    def __init__(self, data):
        self.data = data
        self.elf = ELFFile(io.BytesIO(data))
        # Addresses where imported functions are looked up (the "GOT"),
        # mapped to the function's name. Calls to imports go through there.
        self.got = {}
        for section in self.elf.iter_sections():
            if not isinstance(section, RelocationSection):
                continue
            symbols = self.elf.get_section(section["sh_link"])
            for relocation in section.iter_relocations():
                symbol_index = relocation["r_info_sym"]
                if symbol_index and hasattr(symbols, "get_symbol"):
                    name = symbols.get_symbol(symbol_index).name
                    if name:
                        self.got[relocation["r_offset"]] = name

    def read(self, address, size):
        # An address in the running program is not the same as a position
        # in the file. The "segments" say which part of the file is loaded
        # at which address, so we can translate one into the other.
        for segment in self.elf.iter_segments():
            if segment["p_type"] != "PT_LOAD":
                continue
            start = segment["p_vaddr"]
            if start <= address < start + segment["p_filesz"]:
                offset = segment["p_offset"] + (address - start)
                size = min(size, start + segment["p_filesz"] - address)
                return self.data[offset : offset + size]
        return b""

    def string_at(self, address):
        # A C string: readable characters ending with a zero byte.
        raw = self.read(address, 200)
        end = raw.find(b"\x00")
        if end < 2:
            return None
        text = raw[:end]
        if not all(32 <= byte < 127 or byte in (9, 10) for byte in text):
            return None
        return text.decode("ascii")

    def symbol(self, name):
        # Programs that weren't "stripped" still know their function names.
        table = self.elf.get_section_by_name(".symtab")
        if table:
            for symbol in table.iter_symbols():
                if symbol.name == name and symbol["st_value"]:
                    return symbol["st_value"]
        return None


def new_disassembler():
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True  # also tell us the operands, not only the text
    return md


def rip_target(insn, operand):
    # [rip + 0xe6f] means: 0xe6f bytes after the NEXT instruction.
    return insn.address + insn.size + operand.mem.disp


def import_name(program, md, target):
    """The imported function a call goes to, or None.

    A call to an import goes to a small "PLT stub" whose only job is to
    jump to the address in the GOT. So we read that stub and follow it.
    """
    for insn in md.disasm(program.read(target, 16), target):
        if insn.mnemonic in ("jmp", "bnd jmp") and insn.operands:
            operand = insn.operands[0]
            if operand.type == X86_OP_MEM and operand.mem.base == X86_REG_RIP:
                return program.got.get(rip_target(insn, operand))
    return None


def find_main(program, md):
    """Where main starts, and how we know."""
    address = program.symbol("main")
    if address:
        return address, "main"

    # A stripped program has no names. But the code at the entry point
    # always calls __libc_start_main(main, ...), and on x86-64 the first
    # argument goes in the rdi register. So the last value put in rdi
    # before that call is main.
    entry = program.elf.header["e_entry"]
    rdi = None
    for insn in md.disasm(program.read(entry, 200), entry):
        if insn.mnemonic in ("lea", "mov") and insn.op_str.startswith("rdi,"):
            source = insn.operands[1]
            if source.type == X86_OP_MEM and source.mem.base == X86_REG_RIP:
                rdi = rip_target(insn, source)  # lea rdi, [rip + ...]
            elif source.type == X86_OP_IMM:
                rdi = source.imm  # mov rdi, 0x401136
        if insn.mnemonic == "call":
            break
    if rdi:
        return rdi, "main (found from the entry point)"
    return entry, "the entry point"


def note_for(program, md, insn):
    """A short note in plain words for one instruction, or ""."""
    for operand in insn.operands:
        # A call or jump to a fixed address.
        if operand.type == X86_OP_IMM and (insn.group(1) or insn.group(2)):
            name = import_name(program, md, operand.imm)
            if insn.mnemonic == "call":
                return name or f"function at {operand.imm:#x}"
            return JUMP_WORDS.get(insn.mnemonic, "")
        # Memory relative to rip: an imported function, a string or data.
        if operand.type == X86_OP_MEM and operand.mem.base == X86_REG_RIP:
            target = rip_target(insn, operand)
            if target in program.got:
                return program.got[target]
            text = program.string_at(target)
            if text is not None:
                if len(text) > 60:
                    text = text[:60] + "..."
                return '"' + text.replace("\n", "\\n") + '"'
        # Comparing with a number that is a letter, like cmp al, 0x63: 'c'.
        if insn.mnemonic == "cmp" and operand.type == X86_OP_IMM and 32 < operand.imm < 127:
            return repr(chr(operand.imm))
    return ""


def read_function(program, md, start, budget):
    """The instructions of one function, with notes, and the functions it calls."""
    lines = []
    calls = []  # functions of the program itself that this one calls
    furthest = start  # the furthest place a jump inside this function goes
    for insn in md.disasm(program.read(start, MAX_BYTES), start):
        note = note_for(program, md, insn)
        lines.append({"address": insn.address, "text": f"{insn.mnemonic} {insn.op_str}".strip(), "note": note})

        target = insn.operands[0].imm if insn.operands and insn.operands[0].type == X86_OP_IMM else None
        if target is not None and insn.group(1):  # group 1 = a jump
            furthest = max(furthest, target)
        if insn.mnemonic == "call" and note.startswith("function at"):
            calls.append(target)

        # Where does the function end? At a ret (or a jump away, or a call
        # that never returns) that no earlier jump inside it goes past.
        ends = insn.mnemonic in ("ret", "jmp", "hlt", "ud2") or note in NO_RETURN
        if (ends and insn.address >= furthest) or len(lines) >= budget:
            break
    return lines, calls


def disassemble(data):
    """main and the functions it calls, as assembly with notes.

    Returns a list like [{"name": "main", "address": 4473, "lines": [...]}],
    or None when we can't read this file.
    """
    try:
        program = Program(data)
        if program.elf["e_machine"] != "EM_X86_64":
            return None
        md = new_disassembler()
        start, found = find_main(program, md)

        lines, calls = read_function(program, md, start, MAX_INSTRUCTIONS)
        if not lines:
            return None  # no code where main should be: nothing to show
        functions = [{"name": found, "address": start, "lines": lines}]
        budget = MAX_INSTRUCTIONS - len(lines)

        # The functions main calls often hold the real logic, like a
        # check_password(). Read them too, while the budget lasts.
        for address in dict.fromkeys(calls):  # each once, in the order called
            if budget < 20:
                break
            lines, _ = read_function(program, md, address, budget)
            functions.append({"name": f"function at {address:#x} (called by main)", "address": address, "lines": lines})
            budget -= len(lines)
    except Exception:
        # A broken or unusual file can trip up either library in many
        # ways. Then there is no disassembly, but everything else works.
        return None
    return functions


def as_text(functions):
    """The listing as plain text: each function, one instruction per line."""
    blocks = []
    for function in functions:
        rows = [f"{function['name']}:"]
        for line in function["lines"]:
            row = f"{line['address']:x}  {line['text']}"
            if line["note"]:
                row = f"{row:<44}; {line['note']}"
            rows.append(row)
        blocks.append("\n".join(rows))
    return "\n\n".join(blocks)
