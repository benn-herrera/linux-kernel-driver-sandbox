import re
import unittest

from api_gen import emit_c, emit_lua, model, naming
from api_gen.tests.support import C_BASE_TYPES, FIXTURE, KITCHEN_SINK, MINIMAL, expected_constants, load, mutate, param_lists


class Cdef(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_lua.module(self.api, source_name="xy_api.adef.toml", library="libxy.so")

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

    def test_cdef_declares_exactly_the_header_functions_and_types(self) -> None:
        cdef = emit_c.cdef(self.api)
        self.assertEqual(
            param_lists(cdef, r"(?m)^xy_status "),
            param_lists(emit_c.header(self.api, source_name="x"), r"XY_API xy_status "),
        )
        for t in self.api.typed_consts:
            self.assertIn(f"typedef {C_BASE_TYPES[t.base_type]} xy_{t.name};", cdef)
        for decl in ("struct xy_port_opaque;", "struct xy_link_opaque;", "struct xy_stats {", "struct xy_wrap {"):
            self.assertIn(decl, cdef)

    def test_raw_lists_every_function(self) -> None:
        raw = self.text[self.text.index("M.raw = {") :]
        raw = raw[: raw.index("}")]
        self.assertEqual(
            re.findall(r"^\s+(\w+) = lib\.xy_(\w+),$", raw, re.M),
            [(f.name, f.name) for f in self.api.functions],
        )

    def test_no_functions_yields_an_empty_raw_table(self) -> None:
        api = load(MINIMAL)
        self.assertIn("M.raw = {\n}", emit_lua.module(api, source_name="x", library="libxy.so"))
        emit_c.header(api, source_name="x")


class Constants(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_lua.module(self.api, source_name="xy_api.adef.toml", library="libxy.so")

    def test_constants_equal_the_model_values(self) -> None:
        literals = re.findall(r'^M\.(\w+) = (-?0x[0-9a-f]+|-?[0-9]+|"[^"]*")$', self.text, re.M)
        found = {k: (v[1:-1] if v.startswith('"') else int(v, 0)) for k, v in literals}
        self.assertEqual(found, expected_constants(self.api))

    def test_group_docstring_is_a_comment_above_its_constants(self) -> None:
        lines = self.text.splitlines()
        for group in (*self.api.bit_const_groups, *self.api.const_groups):
            first = next(i for i, line in enumerate(lines) if line.startswith(f"M.{group.entries[0].key.upper()} = "))
            with self.subTest(first=group.entries[0].key):
                if group.docstring:
                    self.assertEqual(lines[first - 1], f"-- {group.docstring}")
                else:
                    self.assertTrue(lines[first - 1].startswith("M."), lines[first - 1])

    def test_loads_the_named_library(self) -> None:
        self.assertIn('ffi.load("libxy.so")', self.text)

    def test_module_namespace_is_unprefixed_and_direct(self) -> None:
        for absent in ("M.XY_", "M.Token", "ffi.C.", "tonumber(lib."):
            self.assertNotIn(absent, self.text)


class Classes(unittest.TestCase):
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

    def test_without_dtor_no_finalizer_and_dtor_is_an_ordinary_method(self) -> None:
        text = mutate(FIXTURE, 'dtor = "destroy_port"', 'class = "data_link"')
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertNotIn("ffi.gc", text)
        self.assertIn("function M.DataLink.new(unit)", text)
        lines = text.splitlines()
        method = lines.index("function M.DataLink.destroy_port(self)")
        self.assertTrue(lines[method + 1].lstrip().startswith("assert(self._handle ~= nil"))


class Refusals(unittest.TestCase):
    def test_constant_and_class_name_clash_is_rejected(self) -> None:
        text = mutate(FIXTURE, "max_units = 16", "io = 16")
        api = load(mutate(text, 'dtor = "destroy_port"', 'dtor = "destroy_port"\nclass = "i_o"'))  # both M.IO
        with self.assertRaises(model.DefinitionError):
            emit_lua.module(api, source_name="x", library="libxy.so")

    def test_no_error_to_str_with_two_return_enums(self) -> None:
        text = mutate(FIXTURE, '[function.spend]\n_return = "status"', '[function.spend]\n_return = "other"')
        text = mutate(text, "[opaque_ref.port]", "[typed_const.other]\nfine = 0\n\n[opaque_ref.port]")
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertNotIn("error_to_str", text)
        self.assertIn("function M.other_to_str(value)", text)


if __name__ == "__main__":
    unittest.main()
