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

from api_gen.tests.support import FIXTURE, load


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

    def test_string_const_rejects_a_quote(self) -> None:
        self.assert_error(FIXTURE.replace('product = "xy widget"', "product = 'xy \"widget\"'"), "string_const.product")

    def test_new_constants_join_the_uniqueness_check(self) -> None:
        self.assert_error(FIXTURE.replace("max_units = 16", "ok = 16"), "XY_OK already defined")
        self.assert_error(FIXTURE.replace('product = "xy widget"', 'max_units = "x"'), "XY_MAX_UNITS already defined")

    def test_class_must_be_an_identifier(self) -> None:
        self.assert_error(FIXTURE.replace('dtor = "destroy_port"', 'dtor = "destroy_port"\nclass = "a-b"'),
                          "class must be an identifier")


class Naming(unittest.TestCase):
    def test_rules(self) -> None:
        self.assertEqual(naming.const_name("tcdl", "cap_compute"), "TCDL_CAP_COMPUTE")
        self.assertEqual(naming.const_name("tcdl", "ok"), "TCDL_OK")
        self.assertEqual(naming.type_name("tcdl", "result"), "tcdl_result")
        self.assertEqual(naming.function_name("tcdl", "create_device"), "tcdl_create_device")
        self.assertEqual(naming.opaque_struct("tcdl", "handle"), "tcdl_handle_opaque")
        self.assertEqual(naming.version_const("tcdl"), "TCDL_API_VERSION")
        self.assertEqual(naming.api_macro("tcdl"), "TCDL_API")
        self.assertEqual(naming.lua_const_name("err_no_device"), "ERR_NO_DEVICE")
        self.assertEqual(naming.upper_camel("my_ns"), "MyNs")


class Model(unittest.TestCase):
    def test_parameter_order_is_document_order(self) -> None:
        fn = next(f for f in load().functions if f.name == "open_port")
        self.assertEqual([p.name for p in fn.params], ["unit", "pport", "pstats", "generation"])

    def test_class_defaults_to_the_name(self) -> None:
        port = next(o for o in load().opaque_refs if o.name == "port")
        self.assertEqual(port.class_name, "port")


class Header(unittest.TestCase):
    def setUp(self) -> None:
        self.text = emit_c.header(load(), source_name="xy_api.adef.toml")

    def test_declarations(self) -> None:
        for expected in (
            "XY_API_VERSION = (0x01 << 24) | (0x02 << 16) | (0x03 << 8) | (0x04 << 0)",
            "  XY_FEAT_B = (1u << 3), /* the b feature */",
            "  XY_FEAT_AB = XY_FEAT_A | XY_FEAT_B\n",
            "/* call outcome */\nenum xy_status {\n  XY_OK = 0,\n  XY_ERR_BUSY = 9, /* try later */\n"
            "  XY_ERR_OTHER = 0x7fffffff\n};",
            "typedef enum xy_status xy_status;",
            "struct xy_port_opaque;\ntypedef struct xy_port_opaque* xy_port;",
            "\tuint32_t count; /* items seen */\n\tuint64_t bytes;\n",
            "typedef struct xy_stats xy_stats;",
            "XY_API xy_status xy_open_port(uint32_t unit, xy_port* pport, xy_stats* pstats, uint32_t* generation);",
            "/* release the port */\nXY_API xy_status xy_destroy_port(xy_port hport);",
            "/* buf: bytes to send */\nXY_API xy_status xy_send(xy_port hport, const void* buf, uint64_t len);",
        ):
            self.assertIn(expected, self.text)

    def test_untyped_and_string_constants(self) -> None:
        untyped = "enum {\n  XY_MAX_UNITS = 16,\n  XY_MAGIC = 0xbeef /* wire magic */\n};\n"
        strings = 'static const char XY_PRODUCT[] = "xy widget";\nstatic const char XY_VENDOR[] = "acme"; /* who made it */\n'
        self.assertIn(untyped, self.text)
        self.assertIn(strings, self.text)
        # untyped after the bit constants; strings after every constant enum, before the types
        self.assertLess(self.text.index("XY_FEAT_AB ="), self.text.index(untyped))
        self.assertLess(self.text.index("typedef enum xy_status"), self.text.index(strings))
        self.assertLess(self.text.index(strings), self.text.index("struct xy_port_opaque;"))

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

    def test_consumer_includes_only_stdint(self) -> None:
        prelude = self.text[: self.text.rindex("#if defined(XY_IMPL)")]
        include_lines = [line for line in prelude.splitlines() if line.startswith(("#include", "# include"))]
        self.assertEqual(include_lines, ["#include <stdint.h>"])

    def test_field_comment_alignment(self) -> None:
        text = emit_c.header(
            load(FIXTURE.replace('bytes = "u64"', 'bytes_total = { type = "u64", docstring = "d" }')),
            source_name="xy_api.adef.toml",
        )
        start = text.index("struct xy_stats {")
        body = text[start : text.index("\n};", start)]
        columns = {line.index("/*") for line in body.splitlines() if "/*" in line}
        self.assertEqual(len(columns), 1)

    def test_banner(self) -> None:
        self.assertIn("GENERATED by vdev/api_gen from xy_api.adef.toml", self.text.splitlines()[0])


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
        self.assertNotIn("XY_PRODUCT", cdef)
        self.assertNotIn("static_assert", cdef)
        self.assertNotIn("assert.h", cdef)
        self.assertFalse([line for line in cdef.splitlines() if line.startswith("#")])

    def test_module_surface(self) -> None:
        for expected in (
            'local lib = ffi.load("libxy.so")',
            "M.API_VERSION = 0x01020304",
            "M.FEAT_B = 8",
            "M.FEAT_AB = 0x9\n",
            "M.MAX_UNITS = 16\n",
            "M.MAGIC = 0xbeef\n",
            "M.OK = 0",
            "M.ERR_BUSY = 9\n",
            "M.ERR_OTHER = 0x7fffffff\n",
            'M.PRODUCT = "xy widget"\n',
            'M.VENDOR = "acme"\n',
            '    [M.ERR_BUSY] = "ERR_BUSY",\n',
            "M.error_to_str = M.status_to_str",
            "    send = lib.xy_send,",
            "    spend = lib.xy_spend,",
            "function M.Port.new(unit)",
            "ffi.gc(pport[0], lib.xy_destroy_port)",
            "function M.Port.send(self, buf)",
            "lib.xy_send(self._handle, buf, #buf)",
            "    if result ~= M.OK then\n",
        ):
            self.assertIn(expected, self.text)
        self.assertNotIn("M.XY_", self.text)
        self.assertNotIn("M.Port.open_port", self.text)
        self.assertNotIn("M.Token", self.text)
        self.assertNotIn("M.Port.spend", self.text)
        self.assertNotIn("tonumber(lib.", self.text)
        self.assertNotIn("ffi.C.", self.text)

    def test_dtor_is_an_explicit_release_method(self) -> None:
        start = self.text.index("function M.Port.destroy_port(self)\n")
        body = self.text[start : self.text.index("\nend\n", start)]
        self.assertNotIn("assert(", body)
        local = body.index("    local handle = self._handle\n")
        guard = body.index("    if handle ~= nil then\n        ffi.gc(handle, nil)\n    end\n")
        call = body.index("lib.xy_destroy_port(handle)")
        drop, check = body.index("    self._handle = nil\n"), body.index("if result ~= M.OK then")
        self.assertLess(local, guard)
        self.assertLess(guard, call)
        self.assertLess(call, drop)
        self.assertLess(drop, check)
        self.assertIn("    return true, nil", body)

    def test_method_asserts_handle_is_live(self) -> None:
        start = self.text.index("function M.Port.send(self, buf)\n")
        body = self.text[start : self.text.index("\nend\n", start)]
        first_statement = body.splitlines()[1].strip()
        self.assertEqual(first_statement, 'assert(self._handle ~= nil, "Port used after destroy_port")')

    def test_constant_and_class_name_clash_is_rejected(self) -> None:
        text = FIXTURE.replace("max_units = 16", "io = 16")
        api = load(text.replace('dtor = "destroy_port"', 'dtor = "destroy_port"\nclass = "i_o"'))  # both M.IO
        with self.assertRaises(model.DefinitionError):
            emit_lua.module(api, source_name="x", library="libxy.so")

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
        text = FIXTURE.replace('dtor = "destroy_port"', 'class = "data_link"')
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertIn("function M.DataLink.new(unit)", text)
        self.assertIn("self._handle = pport[0]\n", text)
        # without a dtor, destroy_port is an ordinary method
        self.assertIn("function M.DataLink.destroy_port(self)", text)
        self.assertIn('assert(self._handle ~= nil, "DataLink has no handle")', text)
        self.assertNotIn("ffi.gc", text)

    def test_no_error_to_str_with_two_return_enums(self) -> None:
        text = FIXTURE.replace('[function.spend]\nreturn = "status"', '[function.spend]\nreturn = "other"')
        text = text.replace("[opaque_ref.port]", "[typed_const.other]\nfine = 0\n\n[opaque_ref.port]")
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertNotIn("error_to_str", text)
        self.assertIn("function M.other_to_str(value)", text)

    def test_inref_struct_is_copied_into_cdata(self) -> None:
        text = FIXTURE + (
            '\n[function.configure]\nreturn = "status"\nhport = "port"\n'
            'cfg = { type = "stats", inref = true }\nlimit = { type = "u32", inref = true }\n'
        )
        module = emit_lua.module(load(text), source_name="x", library="libxy.so")
        for expected in (
            "function M.Port.configure(self, cfg, limit)",
            'local cfg = ffi.new("xy_stats", cfg)',
            'local limit = ffi.new("uint32_t[1]", limit)',
            "lib.xy_configure(self._handle, cfg, limit)",
        ):
            self.assertIn(expected, module)
        header = emit_c.header(load(text), source_name="x")
        self.assertIn("const xy_stats* cfg", header)
        self.assertIn("const uint32_t* limit", header)

    def test_struct_outref_of_method_is_a_table(self) -> None:
        text = FIXTURE + '\n[function.stats_of]\nreturn = "status"\nhport = "port"\nout = { type = "stats", outref = true }\n'
        module = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertIn("count = tonumber(out[0].count)", module)
        self.assertIn("bytes = out[0].bytes", module)
        self.assertNotIn("return out[0], nil", module)

    def test_method_doc_lines(self) -> None:
        self.assertIn("-- buf: bytes to send\nfunction M.Port.send(", self.text)

    def test_nested_struct_is_copied(self) -> None:
        text = FIXTURE.replace("[function.open_port]", '[struct.wrap]\ninner = "stats"\nn = "u32"\n\n[function.open_port]')
        text = text.replace('pstats = { type = "stats"', 'pstats = { type = "wrap"')
        module = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertIn(
            "    self.pstats = {\n        inner = {\n            count = tonumber(pstats.inner.count),\n"
            "            bytes = pstats.inner.bytes,\n        },\n        n = tonumber(pstats.n),\n    }\n",
            module,
        )

    def test_outref_memory_method(self) -> None:
        text = FIXTURE + (
            '\n[function.recv]\nreturn = "status"\nhport = "port"\n'
            'pdst = { type = "memory", outref = true, size = "n" }\nn = "u32"\n'
        )
        module = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertIn("function M.Port.recv(self, n)", module)
        self.assertIn('ffi.new("uint8_t[?]", n)', module)
        self.assertIn("return ffi.string(pdst, n), nil", module)
        start = module.index("function M.Port.send(self, buf)")
        body = module[start : module.index("\nend\n", start)]
        self.assertIn("return true, nil", body)

    def test_composed_of_composed(self) -> None:
        text = FIXTURE.replace('format = "hex" }\n\n[untyped_const]', 'format = "hex" }\nfeat_all = ["feat_ab"]\n\n[untyped_const]')
        api = load(text)
        module = emit_lua.module(api, source_name="x", library="libxy.so")
        header = emit_c.header(api, source_name="x")
        self.assertIn("M.FEAT_ALL = 9", module)
        self.assertIn("XY_FEAT_ALL = XY_FEAT_AB", header)

    def test_new_returns_nil_result(self) -> None:
        start = self.text.index("function M.Port.new(unit)\n")
        body = self.text[start : self.text.index("\nend\n", start)]
        self.assertIn("if result ~= M.OK then\n        return nil, result", body)

    def test_banner(self) -> None:
        self.assertIn("GENERATED by vdev/api_gen from xy_api.adef.toml", self.text.splitlines()[0])


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

    def test_definition_error_exit_2_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text("", encoding="utf-8")
            generated = Path(tmp) / "generated"
            argv = ["api_gen", str(definition), "--generated", str(generated), "--exercise", "tiny_compute"]
            stderr = io.StringIO()
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
                code = api_gen_main.main()
            self.assertEqual(code, 2)
            self.assertTrue(stderr.getvalue().startswith(f"api_gen: {definition}: "))
            self.assertFalse(generated.exists())

    def test_library_override_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            argv = [
                "api_gen", str(definition), "--generated", str(generated),
                "--exercise", "tiny_compute", "--library", "libz.so",
            ]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(api_gen_main.main(), 0)
            lua_text = (generated / "binding" / "xy_api.lua").read_text(encoding="utf-8")
            self.assertIn('ffi.load("libz.so")', lua_text)

        with tempfile.TemporaryDirectory() as tmp:
            text = FIXTURE.replace('library = "libxy.so"\n', "")
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(text, encoding="utf-8")
            generated = Path(tmp) / "generated"
            argv = ["api_gen", str(definition), "--generated", str(generated), "--exercise", "tiny_compute"]
            stderr = io.StringIO()
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
                code = api_gen_main.main()
            self.assertEqual(code, 2)
            self.assertIn("pass --library", stderr.getvalue())


class Gendeps(unittest.TestCase):
    def run_gendeps(self, args: list[str]) -> tuple[int, str]:
        argv = ["api_gen", "gendeps", *args]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            code = api_gen_main.main()
        return code, stdout.getvalue()

    def block(self, *, definition: str, stem: str) -> str:
        paths = api_gen_main.output_paths(stem=stem, exercise="$(BASE)")
        targets = " \\\n".join(f"  $(GEN)/{p}" for p in paths)
        return (
            f"GENERATED := \\\n{targets}\n\n"
            f"$(GENERATED) &: {definition}\n"
            "\tPYTHONPATH=$(API_GEN) PYTHONDONTWRITEBYTECODE=1 python3 -m api_gen"
            " $< --generated $(GEN) --exercise $(BASE)\n"
        )

    def test_one_definition_produces_the_expected_fragment(self) -> None:
        code, out = self.run_gendeps(["a.adef.toml"])
        self.assertEqual(code, 0)
        expected = "# GENERATED by api_gen gendeps; do not edit.\n" + self.block(
            definition="a.adef.toml", stem="a"
        )
        self.assertEqual(out, expected)

    def test_no_definitions_exits_2_with_nothing_on_stdout(self) -> None:
        stderr = io.StringIO()
        argv = ["api_gen", "gendeps"]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(
            stdout
        ), contextlib.redirect_stderr(stderr):
            code = api_gen_main.main()
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "api_gen: gendeps takes exactly one definition\n")

    def test_two_definitions_exits_2_with_nothing_on_stdout(self) -> None:
        stderr = io.StringIO()
        argv = ["api_gen", "gendeps", "a.adef.toml", "b.adef.toml"]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(
            stdout
        ), contextlib.redirect_stderr(stderr):
            code = api_gen_main.main()
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "api_gen: gendeps takes exactly one definition\n")

    def test_bad_name_exits_2_with_nothing_on_stdout(self) -> None:
        code, out = self.run_gendeps(["not_a_definition.txt"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
