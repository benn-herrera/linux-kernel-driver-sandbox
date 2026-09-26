import re
import unittest

from api_gen import emit_binding_lua, emit_c, model, naming
from api_gen.tests.support import (
    C_BASE_TYPES, FIXTURE, KITCHEN_SINK, MINIMAL, expected_constants, header, load, mutate, param_lists,
)


class Cdef(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_binding_lua.emit(self.api, source_name="xy_api.adef.toml", stem="xy_api", library="libxy.so")

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
            param_lists(header(self.api), r"XY_API xy_status "),
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
        self.assertIn("M.raw = {\n}", emit_binding_lua.emit(api, source_name="x", stem="xy_api", library="libxy.so"))


class Constants(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_binding_lua.emit(self.api, source_name="xy_api.adef.toml", stem="xy_api", library="libxy.so")

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
        self.text = emit_binding_lua.emit(self.api, source_name="xy_api.adef.toml", stem="xy_api", library="libxy.so")

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
                if p.ref != "in":
                    count = f"{p.name}_count"
                else:
                    count = f"({p.name} and #{p.name} or 0)" if p.optional else f"#{p.name}"
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
        text = emit_binding_lua.emit(load(text), source_name="x", stem="xy_api", library="libxy.so")
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
        lua = emit_binding_lua.emit(load(text), source_name="x", stem="xy_api", library="libxy.so")
        condition = 'type(limit) == "number" or ffi.istype("uint64_t", limit) or ffi.istype("int64_t", limit)'
        self.assertIn(f'assert({condition}, "Port.configure: limit must be a number or 64-bit cdata")', lua)


class Optional(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_binding_lua.emit(self.api, source_name="xy_api.adef.toml", stem="xy_api", library="libxy.so")

    def test_argument_assert_admits_nil(self) -> None:
        self.assertIn(
            'assert(note == nil or type(note) == "table" or ffi.istype("xy_stats", note), '
            '"Port.annotate: note must be a table or xy_stats or nil")',
            self.text,
        )

    def test_value_is_boxed_only_when_non_nil(self) -> None:
        self.assertIn('local note = note ~= nil and ffi.new("xy_stats", note) or nil', self.text)
        self.assertIn("lib.xy_annotate(self._handle, note)", self.text)

    def test_ctor_cached_outref_ignores_optional(self) -> None:
        self.assertNotIn("pstats ~= nil", self.text)
        self.assertIn('local pstats = ffi.new("xy_stats")\n', self.text)

    def test_memory_in_passes_nil_through_with_a_count_of_0(self) -> None:
        self.assertIn('assert(payload == nil or type(payload) == "string", "Port.probe: payload must be a string or nil")',
                      self.text)
        self.assertIn("lib.xy_probe(self._handle, pmode, payload, (payload and #payload or 0), limit, level, ppeek)",
                      self.text)

    def test_scalar_in_and_inout_are_boxed_only_when_non_nil_and_inout_reads_back_nil(self) -> None:
        self.assertIn('local limit = limit ~= nil and ffi.new("uint32_t[1]", limit) or nil', self.text)
        self.assertIn('local level = level ~= nil and ffi.new("uint32_t[1]", level) or nil', self.text)
        self.assertIn("return tonumber(pmode[0]), (level ~= nil and tonumber(level[0]) or nil), tonumber(ppeek[0]), nil",
                      self.text)


CONVERSION = re.compile(r"^function M\.(\w+)\(value\)$", re.M)


def module(text: str) -> str:
    return emit_binding_lua.emit(load(text), source_name="x", stem="xy_api", library="libxy.so")


class ToString(unittest.TestCase):
    def test_rendered_names(self) -> None:
        self.assertEqual(CONVERSION.findall(module(FIXTURE)), ["feat_to_string", "limit_to_string", "status_to_string"])
        self.assertEqual(
            CONVERSION.findall(module(KITCHEN_SINK)),
            ["access_to_string", "limit_to_string", "status_to_string", "mode_to_string"],
        )

    def test_only_groups_with_the_property_have_a_conversion(self) -> None:
        text = FIXTURE
        for needle in ('_to_string = "feat_to_string"\n', '_to_string = "limit_to_string"\n', '_to_string = "to_string"\n'):
            text = mutate(text, needle, "")
        text = module(text)
        self.assertEqual(CONVERSION.findall(text), [])
        self.assertNotIn("_names", text)
        self.assertNotIn('require("bit")', text)

    def test_bit_is_required_only_for_a_bit_group_conversion(self) -> None:
        self.assertIn('local bit = require("bit")\n', module(FIXTURE))
        self.assertNotIn('require("bit")', module(mutate(FIXTURE, '_to_string = "feat_to_string"\n', "")))

    def test_every_conversion_answers_nil_first(self) -> None:
        api = load(KITCHEN_SINK)
        text = module(KITCHEN_SINK)
        names = CONVERSION.findall(text)
        with_to_string = [t for t in (*api.bit_const_groups, *api.const_groups, *api.typed_consts) if t.to_string]
        self.assertEqual(len(names), len(with_to_string))
        for name in names:
            with self.subTest(name=name):
                self.assertIn(f'function M.{name}(value)\n    if value == nil then return "nil" end\n', text)

    def test_lookup_names_the_last_entry_of_a_shared_value_and_unknown(self) -> None:
        text = module(KITCHEN_SINK)
        self.assertIn('    [M.ERR_AGAIN] = "ERR_AGAIN",\n', text)
        self.assertNotIn("[M.ERR_BUSY]", text)
        self.assertIn('return status_to_string_names[value] or "UNKNOWN_STATUS"\n', text)
        self.assertIn('return limit_to_string_names[value] or "UNKNOWN"\n', text)

    def test_bit_conversion_tests_only_single_bit_entries(self) -> None:
        text = module(KITCHEN_SINK)
        self.assertIn("    if bit.band(value, M.ACC_A) ~= 0 then\n", text)
        self.assertIn("    if bit.band(value, M.ACC_B) ~= 0 then\n", text)
        self.assertNotIn("M.ACC_AB)", text)


class Validate(unittest.TestCase):
    def validate(self, text: str) -> list[str]:
        return emit_binding_lua.validate(load(text))

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

    def test_generated_names_are_reserved_for_parameters_only(self) -> None:
        for name in ("result", "type", "assert", "tonumber", "setmetatable", "string", "self", "h"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(mutate(FIXTURE, 'unit = "u32"', f'{name} = "u32"')),
                    [f"lua: function.open_port.{name}: '{name}' is a name the generated code uses"],
                )
        self.assertEqual(self.validate(mutate(FIXTURE, "status", "result", every=True)), [])

    def test_every_generated_name_is_used_by_the_generated_code(self) -> None:
        text = module(KITCHEN_SINK)
        for name in emit_binding_lua.GENERATED_NAMES:
            with self.subTest(name=name):
                self.assertRegex(text, rf"(?<![\w.]){name}(?!\w)")

    def test_constant_and_class_name_clash(self) -> None:
        text = mutate(FIXTURE, "max_units = 16", "io = 16")
        text = mutate(text, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_class = "i_o"')  # both M.IO
        self.assertEqual(self.validate(text), ["lua: M.IO would be both a constant and a class"])

    def test_member_collision(self) -> None:
        text = mutate(FIXTURE, 'generation = { _type = "u32", _ref = "out" }', 'send = { _type = "u32", _ref = "out" }')
        self.assertEqual(self.validate(text), ["lua: M.Port.send would be both function.send and function.open_port.send"])

    def test_class_collision(self) -> None:
        self.assertEqual(
            self.validate(mutate(KITCHEN_SINK, '_class = "data_link"', '_class = "port"')),
            ["lua: M.Port would be both a class and a class"],
        )

    def test_bit_flag_beyond_signed_32_bits(self) -> None:
        reason = "LuaJIT bit operations are signed 32-bit, so the flag would not equal its own masked result"
        text = mutate(KITCHEN_SINK, "feat_one = 0", "feat_one = 31")
        self.assertEqual(
            self.validate(text),
            [
                f"lua: untyped_bit_const.feat_one: value 0x80000000 exceeds 0x7fffffff; {reason}",
                f"lua: untyped_bit_const.feat_all: value 0x80000008 exceeds 0x7fffffff; {reason}",
            ],
        )
        self.assertEqual(self.validate(mutate(KITCHEN_SINK, "feat_one = 0", "feat_one = 30")), [])

    def test_conversion_name_is_keyword_checked(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, '_to_string = "to_string"', '_to_string = "end"')),
            ["lua: typed_const.status._to_string: 'end' is a Lua keyword"],
        )

    def test_enum_conversion_is_prefixed_so_a_bare_name_does_not_collide(self) -> None:
        self.assertEqual(self.validate(mutate(FIXTURE, '_to_string = "limit_to_string"', '_to_string = "to_string"')), [])

    def test_conversion_collisions(self) -> None:
        for name, message in (
            ("status_to_string", "M.status_to_string would be both untyped_const[0]._to_string and typed_const.status._to_string"),
            ("feat_to_string", "M.feat_to_string would be both untyped_bit_const[0]._to_string and untyped_const[0]._to_string"),
            ("MAX_UNITS", "M.MAX_UNITS would be both a constant and untyped_const[0]._to_string"),
            ("raw", "M.raw would be both untyped_const[0]._to_string and the raw function table"),
            ("Port", "M.Port would be both untyped_const[0]._to_string and a class"),
        ):
            with self.subTest(name=name):
                text = mutate(FIXTURE, '_to_string = "limit_to_string"', f'_to_string = "{name}"')
                self.assertEqual(self.validate(text), [f"lua: {message}"])


if __name__ == "__main__":
    unittest.main()
