import tomllib
import unittest

from api_gen import emit_c, emit_lua, emit_pins, model, naming

FIXTURE = """
[general]
name = "xy_api"
namespace = "xy"
version = [1, 2, 3, 4]
library = "libxy.so"

[untyped_bit_const]
feat_a = 0
feat_b = { value = 3, docstring = "the b feature" }
feat_ab = ["feat_a", "feat_b"]

[typed_const.status]
docstring = "call outcome"
ok = 0
err_busy = { value = 9, docstring = "try later" }

[opaque_ref.port]

[struct.stats]
count = { type = "u32", docstring = "items seen" }
bytes = "u64"

[function.open_port]
return = "status"
unit = "u32"
pport = { type = "port", outref = true }
pstats = { type = "stats", outref = true, nullsafe = true }

[function.destroy_port]
docstring = "release the port"
return = "status"
hport = "port"

[function.send]
return = "status"
hport = "port"
buf = { type = "memory", inref = true, size = "len", docstring = "bytes to send" }
len = "u64"

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
        text = FIXTURE.replace('feat_ab = ["feat_a", "feat_b"]', 'feat_ab = ["feat_a", "feat_c"]')
        self.assert_error(text, "unknown constant 'feat_c'")

    def test_size_must_name_a_sibling_integer(self) -> None:
        self.assert_error(FIXTURE.replace('size = "len"', 'size = "hport"'), "must name a u32 or u64")

    def test_memory_needs_direction(self) -> None:
        self.assert_error(FIXTURE.replace("inref = true, ", ""), "must be inref or outref")

    def test_missing_general(self) -> None:
        self.assert_error("[function]\n", "missing [general] table")


class Naming(unittest.TestCase):
    def test_rules(self) -> None:
        self.assertEqual(naming.const_name("tcdl", "cap_compute"), "TCDL_CAP_COMPUTE")
        self.assertEqual(naming.const_name("tcdl", "ok"), "TCDL_OK")
        self.assertEqual(naming.type_name("tcdl", "result"), "tcdl_result")
        self.assertEqual(naming.function_name("tcdl", "create_device"), "tcdl_create_device")
        self.assertEqual(naming.opaque_struct("tcdl", "handle"), "tcdl_handle_opaque")
        self.assertEqual(naming.version_const("tcdl"), "TCDL_API_VERSION")
        self.assertEqual(naming.api_macro("tcdl"), "TCDL_API")
        self.assertEqual(naming.device_class("tcdl"), "TcdlDevice")
        self.assertEqual(naming.device_class("my_ns"), "MyNsDevice")


class Model(unittest.TestCase):
    def test_parameter_order_is_document_order(self) -> None:
        fn = next(f for f in load().functions if f.name == "open_port")
        self.assertEqual([p.name for p in fn.params], ["unit", "pport", "pstats"])


class Header(unittest.TestCase):
    def setUp(self) -> None:
        self.text = emit_c.header(load(), source_name="xy_api.adef.toml")

    def test_declarations(self) -> None:
        for expected in (
            "XY_API_VERSION = (0x01 << 24) | (0x02 << 16) | (0x03 << 8) | (0x04 << 0)",
            "  XY_FEAT_B = (1u << 3), /* the b feature */",
            "  XY_FEAT_AB = XY_FEAT_A | XY_FEAT_B\n",
            "/* call outcome */\nenum xy_status {\n  XY_OK = 0,\n  XY_ERR_BUSY = 9, /* try later */\n};",
            "typedef enum xy_status xy_status;",
            "struct xy_port_opaque;\ntypedef struct xy_port_opaque* xy_port;",
            "\tuint32_t count; /* items seen */\n\tuint64_t bytes;\n",
            "typedef struct xy_stats xy_stats;",
            "XY_API xy_status xy_open_port(uint32_t unit, xy_port* pport, xy_stats* pstats);",
            "/* release the port */\nXY_API xy_status xy_destroy_port(xy_port hport);",
            "/* buf: bytes to send */\nXY_API xy_status xy_send(xy_port hport, const void* buf, uint64_t len);",
        ):
            self.assertIn(expected, self.text)

    def test_only_permitted_preprocessor_lines(self) -> None:
        allowed = ("#pragma once", "#include", "#if", "#else", "#endif", "# define")
        for line in self.text.splitlines():
            if line.startswith("#"):
                self.assertTrue(line.startswith(allowed), line)


class Pins(unittest.TestCase):
    def test_pins(self) -> None:
        text = emit_pins.pins(load(), source_name="xy_api.adef.toml", stem="xy_api")
        self.assertIn('#include "xy/driver/xy_ioctl.h"\n#include "xy_api.h"\n', text)
        self.assertIn('static_assert(XY_FEAT_A == XYD_FEAT_A, "XY_FEAT_A must match XYD_FEAT_A");', text)
        self.assertEqual(text.count("static_assert"), 1)


class Lua(unittest.TestCase):
    def setUp(self) -> None:
        self.text = emit_lua.module(load(), source_name="xy_api.adef.toml", library="libxy.so")

    def test_cdef_has_no_preprocessor_or_api_macro(self) -> None:
        start = self.text.index("ffi.cdef[[") + len("ffi.cdef[[")
        cdef = self.text[start : self.text.index("]]", start)]
        self.assertIn("xy_status xy_send(", cdef)
        self.assertNotIn("XY_API ", cdef)
        self.assertFalse([line for line in cdef.splitlines() if line.startswith("#")])

    def test_module_surface(self) -> None:
        for expected in (
            'local lib = ffi.load("libxy.so")',
            "M.XY_ERR_BUSY = tonumber(ffi.C.XY_ERR_BUSY)",
            "M.error_to_str = M.status_to_str",
            "    send = lib.xy_send,",
            "function M.XyDevice.new(unit)",
            "ffi.gc(pport[0], lib.xy_destroy_port)",
            "function M.XyDevice.send(self, buf)",
            "lib.xy_send(self._handle, buf, #buf)",
        ):
            self.assertIn(expected, self.text)
        self.assertNotIn("M.XyDevice.destroy_port", self.text)

    def test_memory_without_size_is_rejected(self) -> None:
        api = load(FIXTURE.replace(', size = "len"', ""))
        with self.assertRaises(model.DefinitionError):
            emit_lua.module(api, source_name="x", library="libxy.so")


if __name__ == "__main__":
    unittest.main()
