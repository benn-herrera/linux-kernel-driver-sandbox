import contextlib
import io
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from api_gen import __main__ as api_gen_main
from api_gen import emit_c, emit_lua, model, naming

FIXTURE = """
[general]
namespace = "xy"
version = [1, 2, 3, 4]
library = "libxy.so"

[untyped_bit_const]
feat_a = 0
feat_b = { value = 3, docstring = "the b feature" }
feat_ab = { value = ["feat_a", "feat_b"], format = "hex" }

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


def load(text: str = FIXTURE) -> model.Api:
    return model.from_dict(tomllib.loads(text))


class ModelErrors(unittest.TestCase):
    def assert_error(self, text: str, fragment: str) -> None:
        with self.assertRaises(model.DefinitionError) as caught:
            load(text)
        self.assertIn(fragment, str(caught.exception))

    def test_reserved_key_as_member(self) -> None:
        self.assert_error(FIXTURE.replace("bytes = ", "return = "), "reserved key")

    def test_unknown_type(self) -> None:
        self.assert_error(FIXTURE.replace('unit = "u32"', 'unit = "u16"'), "unknown type 'u16'")

    def test_unknown_return_type(self) -> None:
        self.assert_error(FIXTURE.replace('docstring = "release the port"\nreturn = "status"',
                                          'return = "nope"'), "unknown typed_const 'nope'")

    def test_duplicate_type_name_across_categories(self) -> None:
        self.assert_error(FIXTURE + "\n[opaque_ref.stats]\n", "already defined in")

    def test_pin_names_undefined_constant(self) -> None:
        self.assert_error(FIXTURE + 'feat_z = "XY_FEAT_Z"\n', "undefined untyped_bit_const 'feat_z'")

    def test_composed_constant_must_be_earlier(self) -> None:
        text = FIXTURE.replace('["feat_a", "feat_b"]', '["feat_a", "feat_c"]')
        self.assert_error(text, "unknown constant 'feat_c'")

    def test_size_must_name_a_sibling_integer(self) -> None:
        self.assert_error(FIXTURE.replace('size = "len"', 'size = "hport"'), "must name a u32 or u64")

    def test_memory_needs_direction(self) -> None:
        self.assert_error(FIXTURE.replace("inref = true, ", ""), "must be inref or outref")

    def test_missing_general(self) -> None:
        self.assert_error("[function]\n", "missing [general] table")

    def test_general_name_is_rejected(self) -> None:
        self.assert_error(FIXTURE.replace("[general]\n", '[general]\nname = "xy_api"\n'), "file name is the output stem")

    def test_unknown_format(self) -> None:
        self.assert_error(FIXTURE.replace('format = "hex" }\n\n[opaque', 'format = "oct" }\n\n[opaque'), "format must be one of")

    def test_ctor_needs_one_outref_of_the_opaque(self) -> None:
        self.assert_error(FIXTURE.replace('ctor = "open_port"', 'ctor = "send"'), "exactly one port outref")

    def test_dtor_takes_only_the_opaque(self) -> None:
        self.assert_error(FIXTURE.replace('dtor = "destroy_port"', 'dtor = "send"'), "only parameter is a port")

    def test_dtor_requires_ctor(self) -> None:
        self.assert_error(FIXTURE.replace('ctor = "open_port"\n', ""), "dtor: requires ctor")


class Naming(unittest.TestCase):
    def test_rules(self) -> None:
        self.assertEqual(naming.const_name("tcdl", "cap_compute"), "TCDL_CAP_COMPUTE")
        self.assertEqual(naming.const_name("tcdl", "ok"), "TCDL_OK")
        self.assertEqual(naming.type_name("tcdl", "result"), "tcdl_result")
        self.assertEqual(naming.function_name("tcdl", "create_device"), "tcdl_create_device")
        self.assertEqual(naming.opaque_struct("tcdl", "handle"), "tcdl_handle_opaque")
        self.assertEqual(naming.version_const("tcdl"), "TCDL_API_VERSION")
        self.assertEqual(naming.api_macro("tcdl"), "TCDL_API")
        self.assertEqual(naming.lua_class("tcdl", "Device"), "TcdlDevice")
        self.assertEqual(naming.upper_camel("my_ns"), "MyNs")


class Model(unittest.TestCase):
    def test_parameter_order_is_document_order(self) -> None:
        fn = next(f for f in load().functions if f.name == "open_port")
        self.assertEqual([p.name for p in fn.params], ["unit", "pport", "pstats", "generation"])

    def test_class_defaults_to_upper_camel_of_the_name(self) -> None:
        port = next(o for o in load().opaque_refs if o.name == "port")
        self.assertEqual(port.class_name, "Port")


class Header(unittest.TestCase):
    def setUp(self) -> None:
        self.text = emit_c.header(load(), source_name="xy_api.adef.toml")

    def test_declarations(self) -> None:
        for expected in (
            "XY_API_VERSION = (0x01 << 24) | (0x02 << 16) | (0x03 << 8) | (0x04 << 0)",
            "  XY_FEAT_B = (1u << 3), /* the b feature */",
            "  XY_FEAT_AB = XY_FEAT_A | XY_FEAT_B\n",
            "/* call outcome */\nenum xy_status {\n  XY_OK = 0,\n  XY_ERR_BUSY = 9, /* try later */\n"
            "  XY_ERR_OTHER = 0x7fffffff,\n};",
            "typedef enum xy_status xy_status;",
            "struct xy_port_opaque;\ntypedef struct xy_port_opaque* xy_port;",
            "\tuint32_t count; /* items seen */\n\tuint64_t bytes;\n",
            "typedef struct xy_stats xy_stats;",
            "XY_API xy_status xy_open_port(uint32_t unit, xy_port* pport, xy_stats* pstats, uint32_t* generation);",
            "/* release the port */\nXY_API xy_status xy_destroy_port(xy_port hport);",
            "/* buf: bytes to send */\nXY_API xy_status xy_send(xy_port hport, const void* buf, uint64_t len);",
        ):
            self.assertIn(expected, self.text)

    def test_only_permitted_preprocessor_lines(self) -> None:
        allowed = ("#pragma once", "#include", "#if", "#else", "#endif", "# define", "# include")
        for line in self.text.splitlines():
            if line.startswith("#"):
                self.assertTrue(line.startswith(allowed), line)

    def test_abi_pins_present_with_driver_data(self) -> None:
        # properties of the block, not its exact text: it follows the last declaration,
        # is guarded by the implementation macro, and holds the includes and every pin
        last_function = self.text.rindex("XY_API xy_status xy_send(")
        block = self.text[last_function:]
        guard = block.index("#if defined(XY_IMPL)")
        self.assertEqual(block.count("#if defined(XY_IMPL)"), 1)
        self.assertIn("ABI pins", block[guard:])
        self.assertTrue(block.rstrip().endswith("#endif"))
        for expected in (
            '# include <assert.h>',
            '# include "xy/driver/xy_ioctl.h"',
            'static_assert(XY_FEAT_A == XYD_FEAT_A, "XY_FEAT_A must match XYD_FEAT_A");',
        ):
            self.assertIn(expected, block[guard:])

    def test_abi_pins_absent_without_driver_data(self) -> None:
        text = emit_c.header(load(FIXTURE[: FIXTURE.index("[driver_data]")]), source_name="xy_api.adef.toml")
        self.assertNotIn("ABI pins", text)
        self.assertNotIn("static_assert", text)


class Lua(unittest.TestCase):
    def setUp(self) -> None:
        self.text = emit_lua.module(load(), source_name="xy_api.adef.toml", library="libxy.so")

    def test_cdef_has_no_preprocessor_or_api_macro(self) -> None:
        start = self.text.index("ffi.cdef[[") + len("ffi.cdef[[")
        cdef = self.text[start : self.text.index("]]", start)]
        self.assertIn("xy_status xy_send(", cdef)
        self.assertIn("typedef int32_t xy_status;", cdef)
        self.assertNotIn("XY_API ", cdef)
        self.assertNotIn("enum {", cdef)
        self.assertNotIn("XY_API_VERSION", cdef)
        self.assertNotIn("static_assert", cdef)
        self.assertNotIn("assert.h", cdef)
        self.assertFalse([line for line in cdef.splitlines() if line.startswith("#")])

    def test_module_surface(self) -> None:
        for expected in (
            'local lib = ffi.load("libxy.so")',
            "M.XY_API_VERSION = 0x01020304",
            "M.XY_FEAT_B = 8",
            "M.XY_FEAT_AB = 0x9\n",
            "M.XY_OK = 0",
            "M.XY_ERR_BUSY = 9\n",
            "M.XY_ERR_OTHER = 0x7fffffff\n",
            "M.error_to_str = M.status_to_str",
            "    send = lib.xy_send,",
            "    spend = lib.xy_spend,",
            "function M.XyPort.new(unit)",
            "ffi.gc(pport[0], lib.xy_destroy_port)",
            "function M.XyPort.send(self, buf)",
            "lib.xy_send(self._handle, buf, #buf)",
        ):
            self.assertIn(expected, self.text)
        self.assertNotIn("M.XyPort.destroy_port", self.text)
        self.assertNotIn("M.XyPort.open_port", self.text)
        self.assertNotIn("M.XyToken", self.text)
        self.assertNotIn("M.XyPort.spend", self.text)
        self.assertNotIn("tonumber(lib.", self.text)
        self.assertNotIn("ffi.C.", self.text)

    def test_constructor_caches_every_outref(self) -> None:
        for expected in (
            'local pport = ffi.new("xy_port[1]")',
            'local pstats = ffi.new("xy_stats")',
            'local generation = ffi.new("uint32_t[1]")',
            "lib.xy_open_port(unit, pport, pstats, generation)",
            "    self.pstats = {\n        count = tonumber(pstats.count),\n        bytes = pstats.bytes,\n    }\n",
            "    self.generation = tonumber(generation[0])\n",
        ):
            self.assertIn(expected, self.text)
        self.assertNotIn("to_string", self.text)

    def test_explicit_class_and_no_dtor(self) -> None:
        text = FIXTURE.replace('dtor = "destroy_port"', 'class = "Link"')
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertIn("function M.XyLink.new(unit)", text)
        self.assertIn("self._handle = pport[0]\n", text)
        self.assertIn("function M.XyLink.destroy_port(self)", text)

    def test_no_error_to_str_with_two_return_enums(self) -> None:
        text = FIXTURE.replace('[function.spend]\nreturn = "status"', '[function.spend]\nreturn = "other"')
        text = text.replace("[opaque_ref.port]", "[typed_const.other]\nfine = 0\n\n[opaque_ref.port]")
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertNotIn("error_to_str", text)
        self.assertIn("function M.other_to_str(value)", text)

    def test_memory_without_size_is_rejected(self) -> None:
        api = load(FIXTURE.replace(', size = "len"', ""))
        with self.assertRaises(model.DefinitionError):
            emit_lua.module(api, source_name="x", library="libxy.so")


class Main(unittest.TestCase):
    def run_main(self, definition: Path, generated: Path) -> str:
        argv = ["api_gen", str(definition), "--generated", str(generated), "--exercise", "tiny_compute"]
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
            self.assertEqual(api_gen_main.main(), 0)
        return stderr.getvalue()

    def test_writes_destination_layout_under_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            self.run_main(definition, generated)
            self.assertTrue((generated / "include" / "tiny_compute" / "xy_api.h").is_file())
            self.assertTrue((generated / "binding" / "xy_api.lua").is_file())


class Gendeps(unittest.TestCase):
    def run_gendeps(self, args: list[str]) -> tuple[int, str]:
        argv = ["api_gen", "gendeps", *args]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            code = api_gen_main.main()
        return code, stdout.getvalue()

    def block(self, *, definition: str, stem: str) -> str:
        header, lua = api_gen_main.output_paths(stem=stem, exercise="tiny_compute")
        targets = f"OUT/{header} OUT/{lua}"
        return (
            f"GENERATED += {targets}\n"
            f"{targets} &: {definition}\n"
            "\tPYTHONPATH=$(API_GEN) PYTHONDONTWRITEBYTECODE=1 python3 -m api_gen"
            " $< --generated OUT --exercise tiny_compute\n"
            "\n"
        )

    def test_two_definitions_produce_two_blocks_in_order(self) -> None:
        code, out = self.run_gendeps(
            ["--generated", "OUT", "--exercise", "tiny_compute", "a.adef.toml", "b.adef.toml"]
        )
        self.assertEqual(code, 0)
        expected = (
            "# GENERATED by api_gen gendeps; do not edit.\n"
            + self.block(definition="a.adef.toml", stem="a")
            + self.block(definition="b.adef.toml", stem="b")
        )
        self.assertEqual(out, expected)

    def test_no_definitions_prints_only_the_banner(self) -> None:
        code, out = self.run_gendeps(["--generated", "OUT", "--exercise", "tiny_compute"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "# GENERATED by api_gen gendeps; do not edit.\n")

    def test_bad_name_exits_2_with_nothing_on_stdout(self) -> None:
        code, out = self.run_gendeps(
            ["--generated", "OUT", "--exercise", "tiny_compute", "not_a_definition.txt"]
        )
        self.assertEqual(code, 2)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
