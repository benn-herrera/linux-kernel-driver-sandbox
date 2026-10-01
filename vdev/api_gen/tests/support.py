"""Definitions and helpers shared by the api_gen tests."""

import contextlib
import difflib
import io
import re
import tomllib
import unittest
from pathlib import Path

from api_gen import __main__ as api_gen_main
from api_gen import model
from api_gen.emitters import emit_c

FIXTURE = """
[_general]
_name = "xy_api"
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

[_wrapped_api]
_header = "driver/xy_ioctl.h"
feat_a = "XYD_FEAT_A"
"""

# Every feature the compiled checks exercise, FIXTURE's items among them (its bit-group
# conversion on a group of its own, access_to_string); fake_xy.cpp, fake_xy.rs, check_xy.lua,
# consumer_xy.cpp and consumer_xy.rs are written against it.
KITCHEN_SINK = """
[_general]
_name = "xy_api"
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
err_again = 10
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

[_wrapped_api]
_header = "driver/xy_ioctl.h"
feat_a = "XYD_FEAT_A"
"""

# SPEC.md's `_base_type` spellings, stated independently of naming.BASE_C_TYPES.
C_BASE_TYPES = {"i32": "int32_t", "u32": "uint32_t"}

MINIMAL = '[_general]\n_name = "xy_api"\n_namespace = "xy"\n_version = [0,0,0,1]\n'

EXERCISES = Path("/work/exercises")


def load(text: str = FIXTURE) -> model.Api:
    return model.from_dict(tomllib.loads(text))


def objections(text: str) -> list[str]:
    """Every objection the loader has to definition `text`, in order; none where it loads."""
    try:
        load(text)
    except model.DefinitionError as e:
        return [str(o) for o in e.objections()]
    return []


def assert_objection(test: unittest.TestCase, text: str, message: str) -> None:
    """The loader refuses definition `text` with `message` and nothing else."""
    test.assertEqual(objections(text), [message])


def assert_matches_expected(test: unittest.TestCase, expected: Path, actual: str) -> None:
    """`actual` is the text of the file `expected`, byte for byte, else a unified diff."""
    text = expected.read_text(encoding="utf-8")
    if actual != text:
        test.fail("".join(difflib.unified_diff(
            text.splitlines(keepends=True), actual.splitlines(keepends=True), expected.name, "emitted",
        )))


def header(api: model.Api) -> str:
    """`api`'s C header, as generation writes it from xy_api.adef.toml."""
    return emit_c.emit(api, source_name="xy_api.adef.toml", name="xy_api", library=None, project="xy")


def mutate(text: str, needle: str, replacement: str, *, every: bool = False) -> str:
    """`text` with `needle` replaced: its one occurrence, or with `every` each of them. A
    needle that no longer matches, or that matches more than once without `every`, fails
    loudly."""
    count = text.count(needle)
    assert count >= 1 if every else count == 1, f"fixture holds {count} of {needle!r}"
    return text.replace(needle, replacement)


# FIXTURE with two independent loader errors: two functions whose _return names no
# typed_const, one of them port's _dtor.
TWO_BAD_RETURNS = mutate(
    mutate(FIXTURE, '_docstring = "release the port"\n_return = "status"', '_return = "nope"'),
    '_return = "status"\nhtoken', '_return = "gone"\nhtoken',
)

# FIXTURE without its [_wrapped_api], the last table.
NO_WRAPPED_API = FIXTURE[: FIXTURE.index("[_wrapped_api]")]

# KITCHEN_SINK with what only the Rust outputs' compile gates and a Rust stub built as the
# library exercise: the constructor caching an enum `out`; a method taking an enum by every
# `_ref` the binding passes through a local of the enum's base type; methods taking an opaque
# through `_ref`, `link` with a class and `token` without; a method of `&self` and seven
# parameters, so a stub fn of eight, where clippy's too_many_arguments begins; and a buffer
# whose count type cannot count every slice.
REFS = mutate(
    KITCHEN_SINK, 'generation = { _type = "u32", _ref = "out" }', 'generation = { _type = "mode", _ref = "out" }'
) + """
[function.steer]
_return = "status"
hport = "port"
want = { _type = "mode", _ref = "in" }
cur = { _type = "mode", _ref = "inout" }
hint = { _type = "mode", _ref = "in", _optional = true }
seen = { _type = "mode", _ref = "inout", _optional = true }
last = { _type = "mode", _ref = "out", _optional = true }

[function.link_to]
_return = "status"
hport = "port"
peer = { _type = "link", _ref = "in" }
maybe = { _type = "link", _ref = "in", _optional = true }

[function.relink]
_return = "status"
hport = "port"
cur = { _type = "link", _ref = "inout" }

[function.lend]
_return = "status"
hport = "port"
tok = { _type = "token", _ref = "in" }

[function.wide]
_return = "status"
hport = "port"
a0 = "u8"
a1 = "u8"
a2 = "u8"
a3 = "u8"
a4 = "u8"
a5 = "u8"
a6 = "u8"

[function.send_short]
_return = "status"
hport = "port"
buf = { _type = "memory", _ref = "in", _count = "u8" }
"""


# Five structs whose UpperCamel re-exports take prelude names the relay does not spell, so
# its module-scope check must not refuse them: Default, Drop, String, ToString, TryFrom.
UNSPELLED_PRELUDE_STRUCTS = "".join(
    f'\n[struct.{name}]\nv = "u32"\n' for name in ("default", "drop", "string", "to_string", "try_from")
)


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
