"""Definitions and helpers shared by the api_gen tests."""

import contextlib
import functools
import io
import operator
import re
import sys
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from api_gen import __main__ as api_gen_main
from api_gen import model

FIXTURE = """
[general]
namespace = "xy"
version = [1, 2, 3, 4]
library = "libxy.so"

[untyped_bit_const]
feat_a = 0
feat_b = { value = 3, docstring = "the b feature" }
feat_ab = { value = ["feat_a", "feat_b"], format = "hex" }

[untyped_const]
max_units = 16
magic = { value = 0xbeef, format = "hex", docstring = "wire magic" }

[string_const]
product = "xy widget"
vendor = { value = "acme", docstring = "who made it" }

[typed_const.status]
docstring = "call outcome"
ok = 0
err_busy = { value = 9, docstring = "try later" }
err_other = { value = 0x7fffffff, format = "hex" }

[opaque_ref.port]
ctor = "open_port"
dtor = "destroy_port"

[opaque_ref.token]

[struct.stats]
count = { type = "u32", docstring = "items seen" }
bytes = "u64"

[function.open_port]
return = "status"
unit = "u32"
pport = { type = "port", outref = true }
pstats = { type = "stats", outref = true, nullsafe = true }
generation = { type = "u32", outref = true }

[function.destroy_port]
docstring = "release the port"
return = "status"
hport = "port"

[function.send]
return = "status"
hport = "port"
buf = { type = "memory", inref = true, size = "len", docstring = "bytes to send" }
len = "u64"

[function.spend]
return = "status"
htoken = "token"

[driver_data]
header = "xy/driver/xy_ioctl.h"
[driver_data.const_pins]
feat_a = "XYD_FEAT_A"
"""

# FIXTURE with every feature the compiled checks exercise; fake_xy.cpp, check_xy.lua and
# consumer_xy.cpp are written against it.
KITCHEN_SINK = """
[general]
namespace = "xy"
version = [1, 2, 3, 4]
library = "libxy.so"

[untyped_bit_const]
feat_a = 0
feat_b = { value = 3, docstring = "the b feature" }
feat_ab = { value = ["feat_a", "feat_b"], format = "hex" }
feat_all = ["feat_ab"]

[untyped_const]
max_units = 16
magic = { value = 0xbeef, format = "hex", docstring = "wire magic" }
neg = { value = -5, format = "hex" }

[string_const]
product = "xy widget"
vendor = { value = "acme", docstring = "who made it" }

[typed_const.status]
docstring = "call outcome"
ok = 0
err_busy = { value = 9, docstring = "try later" }
err_other = { value = 0x7fffffff, format = "hex" }
err_again = 9
err_unsupported = 12

[typed_const.mode]
fine = 0
slow = 1

[opaque_ref.port]
docstring = "a port"
ctor = "open_port"
dtor = "destroy_port"

[opaque_ref.token]

[opaque_ref.link]
ctor = "open_link"
class = "data_link"

[struct.stats]
docstring = "counters"
count = { type = "u32", docstring = "items seen" }
bytes = "u64"

[struct.wrap]
inner = "stats"
n = "u32"

[function.open_port]
return = "status"
unit = "u32"
pport = { type = "port", outref = true }
pstats = { type = "stats", outref = true, nullsafe = true }
generation = { type = "u32", outref = true }
pwrap = { type = "wrap", outref = true }

[function.destroy_port]
docstring = "release the port"
return = "status"
hport = "port"

[function.send]
return = "status"
hport = "port"
buf = { type = "memory", inref = true, size = "len", docstring = "bytes to send" }
len = "u64"

[function.spend]
return = "status"
htoken = "token"

[function.recv]
return = "status"
hport = "port"
pdst = { type = "memory", outref = true, size = "n" }
n = "u32"

[function.configure]
return = "status"
hport = "port"
cfg = { type = "stats", inref = true }
limit = { type = "u32", inref = true }
mode = "mode"
who = "token"

[function.stats_of]
return = "status"
hport = "port"
out = { type = "stats", outref = true }
pcount = { type = "u32", outref = true }
plink = { type = "link", outref = true }

[function.open_link]
return = "status"
plink = { type = "link", outref = true }

[function.reset]
return = "status"

[driver_data]
header = "xy/driver/xy_ioctl.h"
[driver_data.const_pins]
feat_a = "XYD_FEAT_A"
"""

MINIMAL = '[general]\nnamespace = "xy"\nversion = [0,0,0,1]\n'

IN_CONTAINER = Path("/work/vdev").is_dir()
CONTAINER_ONLY_REASON = "compiled and executed checks run only in the build container; run `just api-gen-test-vdev`"
container_only = unittest.skipUnless(IN_CONTAINER, CONTAINER_ONLY_REASON)
EXERCISES = Path("/work/exercises")


def load(text: str = FIXTURE) -> model.Api:
    return model.from_dict(tomllib.loads(text))


def mutate(text: str, needle: str, replacement: str) -> str:
    """`text` with `needle` replaced; a needle that no longer matches fails loudly."""
    assert needle in text, f"fixture no longer contains {needle!r}"
    return text.replace(needle, replacement)


def param_lists(text: str, pattern: str) -> dict[str, str]:
    """Function name -> parameter list text, for every `<pattern>xy_<f>(<params>)` in text."""
    return dict(re.findall(pattern + r"xy_(\w+)\(([^)]*)\)", text))


def run_main(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI with `argv` (no program name); return (exit code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with (
        mock.patch.object(sys, "argv", ["api_gen", *argv]),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        code = api_gen_main.main()
    return code, stdout.getvalue(), stderr.getvalue()


def expected_constants(api: model.Api) -> dict[str, int | str]:
    """Every constant's unprefixed name and value, computed from the model alone."""
    bits: dict[str, int] = {}
    for c in api.bit_consts:
        own = 1 << c.bit if c.bit is not None else 0
        bits[c.key] = own | functools.reduce(operator.or_, (bits[p] for p in c.parts), 0)
    out: dict[str, int | str] = {"API_VERSION": api.version_value()}
    out |= {c.key.upper(): bits[c.key] for c in api.bit_consts}
    out |= {c.key.upper(): c.value for c in api.consts}
    out |= {e.key.upper(): e.value for t in api.typed_consts for e in t.entries}
    out |= {c.key.upper(): c.value for c in api.string_consts}
    return out
