"""Definitions and helpers shared by the api_gen tests."""

import contextlib
import io
import re
import tomllib
from pathlib import Path

from api_gen import __main__ as api_gen_main
from api_gen import model
from api_gen.emitters import emit_c

FIXTURE = """
[_general]
_namespace = "xy"
_version = [1, 2, 3, 4]
_library = "libxy.so"

[[untyped_bit_const]]
feat_a = 0
feat_b = { _value = 3, _docstring = "the b feature" }
feat_ab = { _value = ["feat_a", "feat_b"], _format = "hex" }
_to_string = "feat_to_string"

[[untyped_const]]
max_units = 16
magic = { _value = 0xbeef, _format = "hex", _docstring = "wire magic" }
_to_string = "limit_to_string"

[[string_const]]
product = "xy widget"
vendor = { _value = "acme", _docstring = "who made it" }

[typed_const.status]
_docstring = "call outcome"
_to_string = "to_string"
ok = 0
err_busy = { _value = 9, _docstring = "try later" }
err_other = { _value = 0x7fffffff, _format = "hex" }

[opaque_ref.port]
_ctor = "open_port"
_dtor = "destroy_port"

[opaque_ref.token]

[struct.stats]
count = { _type = "u32", _docstring = "items seen" }
bytes = "u64"

[function.open_port]
_return = "status"
unit = "u32"
pport = { _type = "port", _ref = "out" }
pstats = { _type = "stats", _ref = "out", _optional = true }
generation = { _type = "u32", _ref = "out" }

[function.destroy_port]
_docstring = "release the port"
_return = "status"
hport = "port"

[function.send]
_return = "status"
hport = "port"
buf = { _type = "memory", _ref = "in", _count = "u64", _docstring = "bytes to send" }

[function.spend]
_return = "status"
htoken = "token"

[_driver_data]
_header = "xy/driver/xy_ioctl.h"
[_driver_data.const_pins]
feat_a = "XYD_FEAT_A"
"""

# FIXTURE with every feature the compiled checks exercise; fake_xy.cpp, check_xy.lua and
# consumer_xy.cpp are written against it.
KITCHEN_SINK = """
[_general]
_namespace = "xy"
_version = [1, 2, 3, 4]
_library = "libxy.so"

[[untyped_bit_const]]
_docstring = "feature flags"
feat_a = 0
feat_b = { _value = 3, _docstring = "the b feature" }
feat_ab = { _value = ["feat_a", "feat_b"], _format = "hex" }
feat_lit = { _value = ["feat_a", "4"] }

[[untyped_bit_const]]
_base_type = "u32"
feat_one = 0
feat_all = ["feat_one", "8"]

[[untyped_bit_const]]
_docstring = "access flags"
_to_string = "access_to_string"
acc_a = 0
acc_b = 1
acc_ab = ["acc_a", "acc_b"]

[[untyped_const]]
_docstring = "limits"
_to_string = "limit_to_string"
max_units = 16
extra = 4
max_total = ["max_units", "extra"]
neg = { _value = -5, _format = "hex" }
low = -7
floor = { _value = -2147483648, _format = "hex" }
dip = ["max_units", "-3"]

[[untyped_const]]
_docstring = "wire values"
_base_type = "u32"
magic = { _value = 0xbeef, _format = "hex", _docstring = "wire magic" }

[[string_const]]
product = "xy widget"
vendor = { _value = "acme", _docstring = "who made it" }

[typed_const.status]
_docstring = "call outcome"
_to_string = "to_string"
ok = 0
err_busy = { _value = 9, _docstring = "try later" }
err_other = { _value = 0x7fffffff, _format = "hex" }
err_again = 9
err_unsupported = 12
err_floor = { _value = -2147483648, _format = "hex" }

[typed_const.mode]
_base_type = "u32"
_to_string = "to_string"
fine = 0
slow = 1

[opaque_ref]
port = { _docstring = "a port", _ctor = "open_port", _dtor = "destroy_port" }

[opaque_ref.token]

[opaque_ref.link]
_ctor = "open_link"
_class = "data_link"

[boxed_scalar.offset]
_docstring = "a device offset"
_base_type = "u64"

[struct.stats]
_docstring = "counters"
count = { _type = "u32", _docstring = "items seen" }
bytes = "u64"

[struct.wrap]
inner = "stats"
[struct.wrap.n]
_type = "u32"

[function.open_port]
_return = "status"
unit = "u32"
pport = { _type = "port", _ref = "out" }
pstats = { _type = "stats", _ref = "out", _optional = true }
generation = { _type = "u32", _ref = "out" }
pwrap = { _type = "wrap", _ref = "out" }

[function.destroy_port]
_docstring = "release the port"
_return = "status"
hport = "port"

[function.send]
_return = "status"
hport = "port"
buf = { _type = "memory", _ref = "in", _count = "u64", _docstring = "bytes to send" }

[function.spend]
_return = "status"
htoken = "token"

[function.recv]
_return = "status"
hport = "port"
pdst = { _type = "memory", _ref = "out", _count = "u32" }

[function.configure]
_return = "status"
hport = "port"
cfg = { _type = "stats", _ref = "in" }
limit = { _type = "u32", _ref = "in" }
mode = "mode"
who = "token"

[function.stats_of]
_return = "status"
hport = "port"
out = { _type = "stats", _ref = "out" }
pcount = { _type = "u32", _ref = "out" }
plink = { _type = "link", _ref = "out" }

[function.bump]
_docstring = "level + 1, tally.count * 2, each byte of data + 1"
_return = "status"
hport = "port"
level = { _type = "u32", _ref = "inout" }
tally = { _type = "stats", _ref = "inout" }
data = { _type = "memory", _ref = "inout", _count = "u32" }

[function.open_link]
_return = "status"
plink = { _type = "link", _ref = "out" }

[function.annotate]
_docstring = "ok iff note is absent or note.count == 7"
_return = "status"
hport = "port"
note = { _type = "stats", _ref = "in", _optional = true }

[function.reset]
_return = "status"

[function.seek]
_return = "status"
hport = "port"
offset = "u64"

[function.tune]
_docstring = "pnext = big - 1, pdelta = delta - 1; ok iff delta == -3, big == -(1 << 40), small == 200, scale == 0.5"
_return = "status"
hport = "port"
delta = "i32"
big = "i64"
small = "u8"
scale = "f64"
pnext = { _type = "i64", _ref = "out" }
pdelta = { _type = "i32", _ref = "out" }

[function.probe]
_docstring = "pmode = slow, level + 1 and ppeek = 9 where given; ok iff payload is absent or 2 bytes and limit is absent or 3"
_return = "status"
hport = "port"
pmode = { _type = "mode", _ref = "out" }
payload = { _type = "memory", _ref = "in", _count = "u32", _optional = true }
limit = { _type = "u32", _ref = "in", _optional = true }
level = { _type = "u32", _ref = "inout", _optional = true }
ppeek = { _type = "u32", _ref = "out", _optional = true }

[function.echo_offset]
_docstring = "ppos = pos"
_return = "status"
hport = "port"
pos = "offset"
ppos = { _type = "offset", _ref = "out" }

[_driver_data]
_header = "xy/driver/xy_ioctl.h"
[_driver_data.const_pins]
feat_a = "XYD_FEAT_A"
"""

# SPEC.md's `_base_type` spellings, stated independently of naming.BASE_C_TYPES.
C_BASE_TYPES = {"i32": "int32_t", "u32": "uint32_t"}
C_CONST_MACROS = {"i32": "INT32_C", "u32": "UINT32_C"}

MINIMAL = '[_general]\n_namespace = "xy"\n_version = [0,0,0,1]\n'

EXERCISES = Path("/work/exercises")


def load(text: str = FIXTURE) -> model.Api:
    return model.from_dict(tomllib.loads(text))


def header(api: model.Api) -> str:
    """`api`'s C header, as generation writes it from xy_api.adef.toml."""
    return emit_c.emit(api, source_name="xy_api.adef.toml", stem="xy_api", library=None)


def mutate(text: str, needle: str, replacement: str, *, every: bool = False) -> str:
    """`text` with `needle` replaced: its one occurrence, or with `every` each of them. A
    needle that no longer matches, or that matches more than once without `every`, fails
    loudly."""
    count = text.count(needle)
    assert count >= 1 if every else count == 1, f"fixture holds {count} of {needle!r}"
    return text.replace(needle, replacement)


def param_lists(text: str, pattern: str) -> dict[str, str]:
    """Function name -> parameter list text, for every `<pattern>xy_<f>(<params>)` in text."""
    return dict(re.findall(pattern + r"xy_(\w+)\(([^)]*)\)", text))


def run_main(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI with `argv` (no program name); return (exit code, stdout, stderr). A
    usage error exits through argparse's `SystemExit`, whose code is returned the same."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = api_gen_main.main(argv)
        except SystemExit as e:
            code = e.code
    return code, stdout.getvalue(), stderr.getvalue()


def expected_constants(api: model.Api) -> dict[str, int | str]:
    """Every constant's unprefixed name and value, read from the model's own resolved
    values (a composed entry's sum was already computed, and a bit group's overlap-
    checked, by the loader)."""
    out: dict[str, int | str] = {"API_VERSION": api.version_value()}
    out |= {c.name.upper(): c.value for c in api.bit_consts}
    out |= {c.name.upper(): c.value for c in api.consts}
    out |= {e.name.upper(): e.value for t in api.typed_consts for e in t.entries}
    out |= {c.name.upper(): c.value for c in api.string_consts}
    return out
