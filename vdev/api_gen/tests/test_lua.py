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
            first = next(i for i, line in enumerate(lines) if line.startswith(f"M.{group.entries[0].name.upper()} = "))
            with self.subTest(first=group.entries[0].name):
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
            and f.params[0].ref is None
        ]

    def test_class_functions_are_new_the_methods_and_the_dtor(self) -> None:
        for cls, opaque in self.classes():
            with self.subTest(cls=cls):
                found = set(re.findall(rf"^function M\.{cls}\.(\w+)\(", self.text, re.M))
                self.assertEqual(found, {"new"} | {f.name for f in self.methods(opaque)})

    def test_argument_asserts_appear_in_order_with_expected_type_text(self) -> None:
        def expected_type(p: model.Param) -> str:
            """SPEC.md's accepted-type wording for `p`'s own argument, derived
            independently of the emitter."""
            if p.type == "memory":
                base = "a number" if p.ref == "out" else "a string"
                return f"{base} or nil" if p.optional and p.ref == "in" else base
            kind = self.api.kind(p.type)
            if kind in ("struct", "opaque"):
                c_type = naming.type_name(self.api.namespace, p.type)
                base = f"a table or {c_type}" if kind == "struct" else f"a {c_type}"
            else:
                base = "a number or 64-bit cdata" if p.type in ("i64", "u64") else "a number"
            return f"{base} or nil" if p.optional else base

        def visible_args(params: tuple[model.Param, ...]) -> list[model.Param]:
            return [p for p in params if p.type == "memory" or p.ref != "out"]

        for cls, opaque in self.classes():
            ctor = next(f for f in self.api.functions if f.name == opaque.ctor)
            funcs = {"new": ctor.params}
            funcs |= {f.name: f.params[1:] for f in self.methods(opaque)}
            for name, params in funcs.items():
                with self.subTest(cls=cls, function=name):
                    body = re.search(rf"^function M\.{cls}\.{name}\(.*?\nend\n", self.text, re.M | re.S).group()
                    found = re.findall(r'"([^"]+ must be [^"]+)"', body)
                    expected = [
                        f"{cls}.{name}: {p.name}{'_count' if p.type == 'memory' and p.ref == 'out' else ''}"
                        f" must be {expected_type(p)}"
                        for p in visible_args(params)
                    ]
                    self.assertEqual(found, expected)

    def test_c_calls_pass_parameters_in_definition_order(self) -> None:
        # The GC finalizer's call to the dtor is excluded: its argument is whatever the
        # finalizer receives, and check_xy.lua shows the finalizer releasing the handle.
        body = "\n".join(line for line in self.text.splitlines() if "ffi.gc(" not in line)
        calls = dict(re.findall(r"lib\.xy_(\w+)\((.*)\)$", body, re.M))
        ctors = {o.ctor for _, o in self.classes()}
        dtors = {o.dtor for _, o in self.classes()} - {None}
        for fn in self.api.functions:
            if fn.name not in calls:
                continue
            def memory_call(p: model.Param) -> list[str]:
                count = f"#{p.name}" if p.ref == "in" else f"{p.name}_count"
                return [p.name, count]

            expected = [n for p in fn.params for n in (memory_call(p) if p.type == "memory" else [p.name])]
            if fn.name not in ctors:
                expected[0] = "handle" if fn.name in dtors else "self._handle"
            with self.subTest(function=fn.name):
                self.assertEqual(calls[fn.name].split(", ") if calls[fn.name] else [], expected)
        called = ctors | {f.name for _, o in self.classes() for f in self.methods(o)}
        self.assertEqual(set(calls), called)

    def test_lua_arguments_are_every_parameter_but_non_memory_outs(self) -> None:
        def lua_args(params: tuple[model.Param, ...]) -> list[str]:
            return [
                f"{p.name}_count" if p.type == "memory" and p.ref == "out" else p.name
                for p in params
                if p.ref != "out" or p.type == "memory"
            ]

        for cls, opaque in self.classes():
            with self.subTest(cls=cls):
                sigs = dict(re.findall(rf"^function M\.{cls}\.(\w+)\((.*)\)$", self.text, re.M))
                ctor = next(f for f in self.api.functions if f.name == opaque.ctor)
                expected = {"new": lua_args(ctor.params)}
                expected |= {f.name: ["self", *lua_args(f.params[1:])] for f in self.methods(opaque)}
                self.assertEqual({k: v.split(", ") if v else [] for k, v in sigs.items()}, expected)
                if opaque.dtor is not None:
                    self.assertEqual(sigs[opaque.dtor], "self")

    def test_memory_is_marshalled_as_a_lua_string(self) -> None:
        self.assertNotIn("ffi.sizeof(", self.text)
        self.assertIn("function M.Port.send(self, buf)", self.text)
        self.assertIn("lib.xy_send(self._handle, buf, #buf)", self.text)
        self.assertIn("function M.Port.recv(self, pdst_count)", self.text)
        self.assertIn('local pdst = ffi.new("uint8_t[?]", pdst_count)', self.text)
        self.assertIn("lib.xy_recv(self._handle, pdst, pdst_count)", self.text)
        self.assertIn("return ffi.string(pdst, pdst_count), nil", self.text)
        self.assertIn("local data_count = #data", self.text)
        self.assertIn('local data = ffi.new("uint8_t[?]", data_count, data)', self.text)
        self.assertIn("lib.xy_bump(self._handle, level, tally, data, data_count)", self.text)
        self.assertIn("ffi.string(data, data_count), nil", self.text)

    def test_without_dtor_no_finalizer_and_dtor_is_an_ordinary_method(self) -> None:
        text = mutate(FIXTURE, '_dtor = "destroy_port"', '_class = "data_link"')
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertNotIn("ffi.gc", text)
        self.assertIn("function M.DataLink.new(unit)", text)
        lines = text.splitlines()
        method = lines.index("function M.DataLink.destroy_port(self)")
        self.assertTrue(lines[method + 1].lstrip().startswith("assert(self._handle ~= nil"))

    def test_release_never_passes_the_ffi_a_bare_nil_handle(self) -> None:
        body = re.search(r"^function M\.Port\.destroy_port\(self\).*?\nend\n", self.text, re.M | re.S).group()
        self.assertIn('or ffi.new("xy_port")', body)
        self.assertNotIn("lib.xy_destroy_port(self._handle)", body)

    def test_u64_argument_accepts_a_number_or_64bit_cdata(self) -> None:
        text = mutate(KITCHEN_SINK, 'limit = { _type = "u32", _ref = "in" }', 'limit = { _type = "u64", _ref = "in" }')
        lua = emit_lua.module(load(text), source_name="x", library="libxy.so")
        condition = 'type(limit) == "number" or ffi.istype("uint64_t", limit) or ffi.istype("int64_t", limit)'
        self.assertIn(f'assert({condition}, "Port.configure: limit must be a number or 64-bit cdata")', lua)


class Optional(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_lua.module(self.api, source_name="xy_api.adef.toml", library="libxy.so")

    def test_argument_assert_admits_nil(self) -> None:
        self.assertIn(
            'assert(note == nil or type(note) == "table" or ffi.istype("xy_stats", note), '
            '"Port.annotate: note must be a table or xy_stats or nil")',
            self.text,
        )

    def test_value_is_boxed_only_when_non_nil(self) -> None:
        self.assertIn('local note = note ~= nil and ffi.new("xy_stats", note) or nil', self.text)
        self.assertIn("lib.xy_annotate(self._handle, note)", self.text)

    def test_ctor_cached_outref_ignores_the_hint(self) -> None:
        self.assertNotIn("pstats ~= nil", self.text)
        self.assertIn('local pstats = ffi.new("xy_stats")\n', self.text)

    def test_by_value_optional_is_refused(self) -> None:
        text = mutate(KITCHEN_SINK, 'mode = "mode"', 'mode = { _type = "mode", _optional = true }')
        self.assertEqual(
            emit_lua.validate(load(text)),
            ["lua: function.configure.mode: optional needs a pointer parameter"],
        )


class ErrorToStr(unittest.TestCase):
    def test_no_error_to_str_with_two_return_enums(self) -> None:
        text = mutate(FIXTURE, '[function.spend]\n_return = "status"', '[function.spend]\n_return = "other"')
        text = mutate(text, "[opaque_ref.port]", "[typed_const.other]\nfine = 0\n\n[opaque_ref.port]")
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertNotIn("error_to_str", text)
        self.assertIn("function M.other_to_str(value)", text)


class ToStr(unittest.TestCase):
    def test_nil_maps_to_the_zero_valued_entry(self) -> None:
        text = emit_lua.module(load(KITCHEN_SINK), source_name="x", library="libxy.so")
        self.assertIn(
            'function M.status_to_str(value)\n    if value == nil then return "OK" end\n'
            "    return status_names[value]\nend\n",
            text,
        )

    def test_enum_with_no_zero_entry_has_no_nil_clause(self) -> None:
        text = mutate(KITCHEN_SINK, "fine = 0", "fine = 5")
        text = emit_lua.module(load(text), source_name="x", library="libxy.so")
        self.assertIn("function M.mode_to_str(value)\n    return mode_names[value]\nend\n", text)


class Validate(unittest.TestCase):
    def validate(self, text: str) -> list[str]:
        return emit_lua.validate(load(text))

    def test_kitchen_sink_has_no_objection(self) -> None:
        self.assertEqual(self.validate(KITCHEN_SINK), [])

    def test_lua_keyword_as_name(self) -> None:
        for text, message in (
            (mutate(FIXTURE, "bytes = ", "end = "), "lua: struct.stats.end: 'end' is a Lua keyword"),
            (mutate(FIXTURE, 'unit = "u32"', 'local = "u32"'), "lua: function.open_port.local: 'local' is a Lua keyword"),
            (FIXTURE + '\n[function.end]\n_return = "status"\n', "lua: function.end: 'end' is a Lua keyword"),
        ):
            with self.subTest(message=message):
                self.assertIn(message, self.validate(text))

    def test_c_and_cpp_keywords_are_not_its_objection(self) -> None:
        self.assertEqual(self.validate(mutate(FIXTURE, "bytes = ", "int = ")), [])
        self.assertEqual(self.validate(mutate(FIXTURE, "bytes = ", "class = ")), [])

    def test_generated_locals_are_reserved_for_parameters_only(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'unit = "u32"', 'result = "u32"')),
            ["lua: function.open_port.result: 'result' is a name the generated code binds"],
        )
        self.assertEqual(self.validate(mutate(FIXTURE, "status", "result")), [])

    def test_constant_and_class_name_clash(self) -> None:
        text = mutate(FIXTURE, "max_units = 16", "io = 16")
        text = mutate(text, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_class = "i_o"')  # both M.IO
        self.assertEqual(self.validate(text), ["lua: M.IO would be both a constant and a class"])

    def test_member_collision(self) -> None:
        text = mutate(FIXTURE, 'generation = { _type = "u32", _ref = "out" }', 'send = { _type = "u32", _ref = "out" }')
        self.assertEqual(self.validate(text), ["lua: M.Port.send would be defined more than once"])


if __name__ == "__main__":
    unittest.main()
