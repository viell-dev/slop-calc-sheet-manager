"""gdb helper for #8: print OUString members reachable from callee-saved registers per frame.

LibreOffice release builds have no debug symbols; this identifies objects (toolbar resource
names, command URLs) by scanning their first words for rtl_uString pointers.
"""

import gdb

REGISTERS = ("rbx", "rbp", "r12", "r13", "r14", "r15")


def read_word(address):
    memory = gdb.selected_inferior().read_memory(address, 8).tobytes()
    return int.from_bytes(memory, "little")


def as_oustring(pointer):
    try:
        header = gdb.selected_inferior().read_memory(pointer, 8).tobytes()
        length = int.from_bytes(header[4:8], "little", signed=True)
        if not 3 <= length <= 200:
            return None
        text = gdb.selected_inferior().read_memory(pointer + 8, 2 * length).tobytes()
        value = text.decode("utf-16-le")
    except (gdb.MemoryError, UnicodeDecodeError, OverflowError):
        return None
    return value if all(32 <= ord(c) < 127 for c in value) else None


def scan(address, words=96):
    found = []
    for index in range(words):
        try:
            word = read_word(address + 8 * index)
        except (gdb.MemoryError, OverflowError):
            break
        value = as_oustring(word)
        if value:
            found.append(f"+0x{8 * index:x}={value!r}")
    return found


def frames(numbers):
    for number in numbers:
        try:
            gdb.execute(f"frame {number}", to_string=True)
            frame = gdb.selected_frame()
        except gdb.error as error:
            print(f"frame {number}: {error}")
            continue
        print(f"== frame {number} pc={frame.pc():#x} {frame.name()}")
        for register in REGISTERS:
            try:
                value = int(frame.read_register(register)) & (2**64 - 1)
            except (gdb.error, ValueError):
                continue
            strings = scan(value) if value > 0x10000 else []
            print(f"   {register}={value:#x} {' '.join(strings)}")
