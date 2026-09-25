import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api_gen import __main__ as api_gen_main
from api_gen import emit_c, emit_cpp_stub, emit_cpp_wrapper, emit_lua, model, naming

from api_gen.tests.support import (
    FIXTURE,
    KITCHEN_SINK,
    expected_constants,
    load,
    mutate,
    param_lists,
    run_main,
)


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
        self.api = load(KITCHEN_SINK)
        self.text = emit_c.header(self.api, source_name="xy_api.adef.toml")

    def test_type_mapping_follows_the_spec_table(self) -> None:
        F, T = False, True
        rows = (
            (("u32", F, F), "uint32_t"),
            (("u64", F, F), "uint64_t"),
            (("status", F, F), "xy_status"),
            (("stats", F, F), "xy_stats"),
            (("port", F, F), "xy_port"),
            (("stats", F, T), "const xy_stats*"),
            (("stats", T, F), "xy_stats*"),
            (("u32", T, F), "uint32_t*"),
            (("u32", F, T), "const uint32_t*"),
            (("memory", F, T), "const void*"),
            (("memory", T, F), "void*"),
        )
        for (type_name, outref, inref), expected in rows:
            param = model.Param(
                name="p", type=type_name, outref=outref, inref=inref, nullsafe=False,
                size="n" if type_name == "memory" else None, docstring=None,
            )
            with self.subTest(type=type_name, outref=outref, inref=inref):
                self.assertEqual(emit_c.param_type(self.api, param), expected)

    def test_functions_declared_in_document_order_with_parameters_in_order(self) -> None:
        decls = param_lists(self.text, r"XY_API xy_status ")
        self.assertEqual(list(decls), [f.name for f in self.api.functions])
        for f in self.api.functions:
            with self.subTest(function=f.name):
                if f.params:
                    names = [s.rsplit(" ", 1)[1] for s in decls[f.name].split(", ")]
                    self.assertEqual(names, [p.name for p in f.params])
                else:
                    self.assertEqual(decls[f.name], "void")

    def test_bit_constants_use_the_spec_spelling(self) -> None:
        self.assertRegex(self.text, r"XY_FEAT_B = \(1u << 3\)")
        self.assertIn("XY_FEAT_AB = XY_FEAT_A | XY_FEAT_B", self.text)
        self.assertIn("XY_FEAT_ALL = XY_FEAT_AB", self.text)

    def test_constant_blocks_precede_types_in_spec_order(self) -> None:
        markers = (
            "XY_API_VERSION", "XY_FEAT_A =", "XY_MAX_UNITS", "enum xy_status", "static const char XY_PRODUCT",
            "struct xy_port_opaque;", "struct xy_stats {", "XY_API xy_status xy_open_port(",
        )
        indices = [self.text.index(m) for m in markers]
        self.assertEqual(indices, sorted(set(indices)))

    def test_docstrings_placed_per_spec(self) -> None:
        lines = self.text.splitlines()

        def index_of(fragment: str) -> int:
            return next(i for i, line in enumerate(lines) if fragment in line)

        self.assertEqual(lines[index_of("enum xy_status {") - 1], "/* call outcome */")
        self.assertIn("/* try later */", lines[index_of("XY_ERR_BUSY = 9")])
        self.assertIn("/* items seen */", lines[index_of("uint32_t count;")])
        self.assertIn("buf: bytes to send", lines[index_of("XY_API xy_status xy_send(") - 1])
        self.assertEqual(lines[index_of("XY_API xy_status xy_destroy_port(") - 1], "/* release the port */")

    def test_only_permitted_preprocessor_lines(self) -> None:
        allowed = ("#pragma once", "#include", "#if", "#else", "#endif", "# define", "# include")
        for line in self.text.splitlines():
            if line.startswith("#"):
                self.assertTrue(line.startswith(allowed), line)

    def test_abi_pins_present_with_driver_data(self) -> None:
        block = self.text[self.text.rindex("XY_API xy_status ") :]
        self.assertEqual(block.count("#if defined(XY_IMPL)"), 1)
        block = block[block.index("#if defined(XY_IMPL)") :]
        self.assertIn("# include <assert.h>", block)
        self.assertIn('# include "xy/driver/xy_ioctl.h"', block)
        self.assertRegex(block, r"static_assert\(XY_FEAT_A == XYD_FEAT_A, \"[^\"]+\"\);")

    def test_abi_pins_absent_without_driver_data(self) -> None:
        text = emit_c.header(load(FIXTURE[: FIXTURE.index("[driver_data]")]), source_name="xy_api.adef.toml")
        self.assertNotIn("ABI pins", text)
        self.assertNotIn("static_assert", text)

    def test_consumer_includes_only_stdint(self) -> None:
        prelude = self.text[: self.text.rindex("#if defined(XY_IMPL)")]
        include_lines = [line for line in prelude.splitlines() if line.startswith(("#include", "# include"))]
        self.assertEqual(include_lines, ["#include <stdint.h>"])

    def test_banner(self) -> None:
        self.assertIn("GENERATED by vdev/api_gen from xy_api.adef.toml", self.text.splitlines()[0])


class Lua(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_lua.module(self.api, source_name="xy_api.adef.toml", library="libxy.so")

    def classes(self) -> list[tuple[str, model.OpaqueRef]]:
        """(Lua class name, opaque) for every opaque that names a ctor."""
        return [(naming.upper_camel(o.class_name), o) for o in self.api.opaque_refs if o.ctor is not None]

    def methods(self, opaque: model.OpaqueRef) -> list[model.Function]:
        """Functions other than the ctor taking the opaque by value first: the dtor included."""
        return [
            f for f in self.api.functions
            if f.name != opaque.ctor and f.params and f.params[0].type == opaque.name
            and not (f.params[0].inref or f.params[0].outref)
        ]

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

    def test_loads_the_named_library(self) -> None:
        self.assertIn('ffi.load("libxy.so")', self.text)

    def test_constants_equal_the_model_values(self) -> None:
        literals = re.findall(r'^M\.(\w+) = (-?0x[0-9a-f]+|-?[0-9]+|"[^"]*")$', self.text, re.M)
        found = {k: (v[1:-1] if v.startswith('"') else int(v, 0)) for k, v in literals}
        self.assertEqual(found, expected_constants(self.api))

    def test_module_namespace_is_unprefixed_and_direct(self) -> None:
        for absent in ("M.XY_", "M.Token", "ffi.C.", "tonumber(lib."):
            self.assertNotIn(absent, self.text)

    def test_raw_lists_every_function(self) -> None:
        raw = self.text[self.text.index("M.raw = {") :]
        raw = raw[: raw.index("}")]
        self.assertEqual(
            re.findall(r"^\s+(\w+) = lib\.xy_(\w+),$", raw, re.M),
            [(f.name, f.name) for f in self.api.functions],
        )

    def test_class_functions_are_new_the_methods_and_the_dtor(self) -> None:
        for cls, opaque in self.classes():
            with self.subTest(cls=cls):
                found = set(re.findall(rf"^function M\.{cls}\.(\w+)\(", self.text, re.M))
                self.assertEqual(found, {"new"} | {f.name for f in self.methods(opaque)})

    def test_c_calls_pass_parameters_in_definition_order(self) -> None:
        # The GC finalizer's call to the dtor is excluded: its argument is whatever the
        # finalizer receives, and check_xy.lua shows the finalizer releasing the handle.
        body = "\n".join(line for line in self.text.splitlines() if "ffi.gc(" not in line)
        calls = dict(re.findall(r"lib\.xy_(\w+)\(([^)]*)\)", body))
        ctors = {o.ctor for _, o in self.classes()}
        dtors = {o.dtor for _, o in self.classes()} - {None}
        for fn in self.api.functions:
            if fn.name not in calls:
                continue
            sizes = {p.size: p.name for p in fn.params if p.type == "memory" and p.inref}
            expected = []
            for i, p in enumerate(fn.params):
                if i == 0 and fn.name not in ctors:
                    expected.append("handle" if fn.name in dtors else "self._handle")
                elif p.name in sizes:
                    expected.append(f"#{sizes[p.name]}")
                else:
                    expected.append(p.name)
            with self.subTest(function=fn.name):
                self.assertEqual(calls[fn.name].split(", ") if calls[fn.name] else [], expected)
        called = ctors | {f.name for _, o in self.classes() for f in self.methods(o)}
        self.assertEqual(set(calls), called)

    def test_lua_arguments_are_non_outref_parameters_minus_inref_sizes(self) -> None:
        def lua_args(fn: model.Function, params: tuple[model.Param, ...]) -> list[str]:
            sizes = {p.size for p in fn.params if p.type == "memory" and p.inref}
            return [p.name for p in params if not p.outref and p.name not in sizes]

        for cls, opaque in self.classes():
            with self.subTest(cls=cls):
                sigs = dict(re.findall(rf"^function M\.{cls}\.(\w+)\((.*)\)$", self.text, re.M))
                ctor = next(f for f in self.api.functions if f.name == opaque.ctor)
                expected = {"new": lua_args(ctor, ctor.params)}
                expected |= {f.name: ["self", *lua_args(f, f.params[1:])] for f in self.methods(opaque)}
                self.assertEqual({k: v.split(", ") if v else [] for k, v in sigs.items()}, expected)
                if opaque.dtor is not None:
                    self.assertEqual(sigs[opaque.dtor], "self")

    def test_cdef_declares_exactly_the_header_functions_and_types(self) -> None:
        cdef = emit_c.cdef(self.api)
        self.assertEqual(
            param_lists(cdef, r"(?m)^xy_status "),
            param_lists(emit_c.header(self.api, source_name="x"), r"XY_API xy_status "),
        )
        for t in self.api.typed_consts:
            self.assertIn(f"typedef int32_t xy_{t.name};", cdef)
        for decl in ("struct xy_port_opaque;", "struct xy_link_opaque;", "struct xy_stats {", "struct xy_wrap {"):
            self.assertIn(decl, cdef)

    def test_constant_and_class_name_clash_is_rejected(self) -> None:
        text = FIXTURE.replace("max_units = 16", "io = 16")
        api = load(text.replace('dtor = "destroy_port"', 'dtor = "destroy_port"\nclass = "i_o"'))  # both M.IO
        with self.assertRaises(model.DefinitionError):
            emit_lua.module(api, source_name="x", library="libxy.so")

    def test_without_dtor_no_finalizer_and_dtor_is_an_ordinary_method(self) -> None:
        text = mutate(FIXTURE, 'dtor = "destroy_port"', 'class = "data_link"')
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertNotIn("ffi.gc", text)
        self.assertIn("function M.DataLink.new(unit)", text)
        lines = text.splitlines()
        method = lines.index("function M.DataLink.destroy_port(self)")
        self.assertTrue(lines[method + 1].lstrip().startswith("assert(self._handle ~= nil"))

    def test_no_error_to_str_with_two_return_enums(self) -> None:
        text = FIXTURE.replace('[function.spend]\nreturn = "status"', '[function.spend]\nreturn = "other"')
        text = text.replace("[opaque_ref.port]", "[typed_const.other]\nfine = 0\n\n[opaque_ref.port]")
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertNotIn("error_to_str", text)
        self.assertIn("function M.other_to_str(value)", text)

    def test_banner(self) -> None:
        self.assertIn("GENERATED by vdev/api_gen from xy_api.adef.toml", self.text.splitlines()[0])


class Main(unittest.TestCase):
    def test_writes_every_output_equal_to_its_emitter_and_reports_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", "tiny_compute"])
            self.assertEqual(code, 0)
            api, source = load(FIXTURE), "xy_api.adef.toml"
            expected = (
                emit_c.header(api, source_name=source),
                emit_cpp_wrapper.wrapper(api, source_name=source, stem="xy_api"),
                emit_lua.module(api, source_name=source, library="libxy.so"),
                emit_cpp_stub.stub(api, source_name=source, stem="xy_api"),
            )
            relpaths = api_gen_main.output_paths(stem="xy_api", exercise="tiny_compute")
            for relpath, text in zip(relpaths, expected, strict=True):
                with self.subTest(output=str(relpath)):
                    self.assertEqual((generated / relpath).read_text(encoding="utf-8"), text)
                    self.assertIn(str(relpath), stderr)
            self.assertEqual(stderr.count("\n"), 1)

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

    def test_library_flag_overrides_the_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, _ = run_main([
                str(definition), "--generated", str(generated), "--exercise", "tiny_compute", "--library", "libz.so",
            ])
            self.assertEqual(code, 0)
            lua_text = (generated / "binding" / "xy_api.lua").read_text(encoding="utf-8")
            self.assertIn('ffi.load("libz.so")', lua_text)

    def test_missing_library_exits_2_with_nothing_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(mutate(FIXTURE, 'library = "libxy.so"\n', ""), encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", "tiny_compute"])
            self.assertEqual(code, 2)
            self.assertIn("pass --library", stderr)
            self.assertFalse(generated.exists())


class Gendeps(unittest.TestCase):
    def run_gendeps(self, args: list[str]) -> tuple[int, str]:
        argv = ["api_gen", "gendeps", *args]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            code = api_gen_main.main()
        return code, stdout.getvalue()

    def test_fragment_lists_the_output_paths_in_one_grouped_rule(self) -> None:
        code, out = self.run_gendeps(["a.adef.toml"])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "# GENERATED by api_gen gendeps; do not edit.")
        targets = re.search(r"GENERATED := \\\n((?:  .*\\\n)*  .*)\n", out).group(1)
        self.assertEqual(
            [t.strip().rstrip(" \\") for t in targets.splitlines()],
            [f"$(GEN)/{p}" for p in api_gen_main.output_paths(stem="a", exercise="$(BASE)")],
        )
        self.assertIn("$(GENERATED) &: a.adef.toml\n\t", out)

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
