import re
import unittest

from api_gen import model, naming
from api_gen.emitters import emit_binding_lua
from api_gen.tests.support import (
    C_BASE_TYPES, DOCUMENTED_FUNCTION_GROUPS, FIXTURE, KITCHEN_SINK, header, load, mutate, param_lists,
)


class Cdef(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_binding_lua.emit(self.api, source_name="xy_api.adef.toml", name="xy_api", library="libxy.so", project="xy")

    def cdef(self) -> str:
        start = self.text.index("ffi.cdef[[") + len("ffi.cdef[[")
        return self.text[start : self.text.index("]]", start)]

    def test_cdef_has_no_preprocessor_or_api_macro(self) -> None:
        cdef = self.cdef()
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
        cdef = self.cdef()
        self.assertEqual(
            param_lists(cdef, r"(?m)^xy_status "),
            param_lists(header(self.api), r"XY_API xy_status "),
        )
        for t in self.api.typed_consts:
            self.assertIn(f"typedef {C_BASE_TYPES[t.base_type]} xy_{t.name};", cdef)
        for decl in (
            "struct xy_port_opaque;", "struct xy_link_opaque;", "typedef struct xy_offset { uint64_t value; } xy_offset;",
            "struct xy_stats {", "struct xy_wrap {",
        ):
            self.assertIn(decl, cdef)

    def test_raw_lists_every_function(self) -> None:
        raw = self.text[self.text.index("M.raw = {") :]
        raw = raw[: raw.index("}")]
        self.assertEqual(
            re.findall(r"^\s+(\w+) = lib\.xy_(\w+),$", raw, re.M),
            [(f.name, f.name) for f in self.api.functions],
        )


class Constants(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_binding_lua.emit(self.api, source_name="xy_api.adef.toml", name="xy_api", library="libxy.so", project="xy")

    def test_group_docstring_is_a_comment_above_its_constants(self) -> None:
        lines = self.text.splitlines()
        for group in (*self.api.bit_const_groups, *self.api.const_groups):
            first = next(i for i, line in enumerate(lines) if line.startswith(f"M.{group.entries[0].name.upper()} = "))
            with self.subTest(first=group.entries[0].name):
                if group.docstring:
                    self.assertEqual(lines[first - 1], f"-- {group.docstring}")
                else:
                    self.assertTrue(lines[first - 1].startswith("M."), lines[first - 1])


class Classes(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_binding_lua.emit(self.api, source_name="xy_api.adef.toml", name="xy_api", library="libxy.so", project="xy")

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
                scalar = next((b.base_type for b in self.api.boxed_scalars if b.name == p.type), p.type)
                base = "a number or 64-bit cdata" if scalar in ("i64", "u64") else "a number"
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

    def test_without_dtor_no_finalizer_and_dtor_is_an_ordinary_method(self) -> None:
        text = mutate(FIXTURE, '_dtor = "destroy_port"', '_class = "data_link"')
        text = emit_binding_lua.emit(load(text), source_name="x", name="xy_api", library="libxy.so", project="xy")
        self.assertNotIn("ffi.gc", text)
        self.assertIn("function M.DataLink.new(unit)", text)
        lines = text.splitlines()
        method = lines.index("function M.DataLink.destroy_port(self)")
        self.assertTrue(lines[method + 1].lstrip().startswith("assert(self._handle ~= nil"))


class BoxedScalar(unittest.TestCase):
    def setUp(self) -> None:
        self.text = module(KITCHEN_SINK)

    def test_an_out_returns_the_unboxed_value(self) -> None:
        self.assertIn('    local ppos = ffi.new("xy_offset")\n', self.text)
        self.assertIn("    return ppos.value, nil\n", self.text)
        narrow = module(mutate(KITCHEN_SINK, '_base_type = "u64"', '_base_type = "u32"'))
        self.assertIn("    return tonumber(ppos.value), nil\n", narrow)
        self.assertIn('assert(type(pos) == "number", "Port.echo_offset: pos must be a number")', narrow)

    def test_a_reference_boxes_into_the_struct_not_an_array(self) -> None:
        text = module(KITCHEN_SINK + (
            '\n[function.move]\n_return = "status"\nhport = "port"\n'
            'src = { _type = "offset", _ref = "in" }\ndst = { _type = "offset", _ref = "inout", _optional = true }\n'
        ))
        self.assertIn('    local src = ffi.new("xy_offset", src)\n', text)
        self.assertIn('    local dst = dst ~= nil and ffi.new("xy_offset", dst) or nil\n', text)
        self.assertIn("    return (dst ~= nil and dst.value or nil), nil\n", text)

    def test_a_struct_field_stays_a_copy_of_the_ffi_struct(self) -> None:
        text = module(mutate(KITCHEN_SINK, "[struct.wrap.n]", 'at = "offset"\n[struct.wrap.n]'))
        self.assertIn('        at = ffi.new("xy_offset", pwrap.at),\n', text)


CONVERSION = re.compile(r"^function M\.(\w+)\(value\)$", re.M)


def module(text: str) -> str:
    return emit_binding_lua.emit(load(text), source_name="x", name="xy_api", library="libxy.so", project="xy")


class ToString(unittest.TestCase):
    def test_only_groups_with_the_property_have_a_conversion(self) -> None:
        text = FIXTURE
        for needle in ('_to_string = "feat_to_string"\n', '_to_string = "limit_to_string"\n', '_to_string = "to_string"\n'):
            text = mutate(text, needle, "")
        text = module(text)
        self.assertEqual(CONVERSION.findall(text), [])
        self.assertNotIn("_names", text)
        self.assertNotIn('require("bit")', text)

    def test_lookup_names_the_last_entry_of_a_plain_group_shared_value_and_unknown(self) -> None:
        text = module(mutate(KITCHEN_SINK, "extra = 4\n", "extra = 16\n"))
        self.assertIn('    [M.EXTRA] = "EXTRA",\n', text)
        self.assertNotIn("[M.MAX_UNITS]", text)
        self.assertIn('    [M.ERR_BUSY] = "ERR_BUSY",\n', text)
        self.assertIn('return status_to_string_names[value] or "UNKNOWN_STATUS"\n', text)
        self.assertIn('return limit_to_string_names[value] or "UNKNOWN"\n', text)


class Validate(unittest.TestCase):
    def validate(self, text: str) -> list[str]:
        return emit_binding_lua.validate(load(text))

    def test_lua_keyword_as_name(self) -> None:
        for text, message in (
            (mutate(FIXTURE, "bytes = ", "end = "), "lua: struct.stats.end: 'end' is a Lua keyword"),
            (mutate(FIXTURE, 'unit = "u32"', 'local = "u32"'), "lua: function.open_port.local: 'local' is a Lua keyword"),
            (FIXTURE + '\n[function.end]\n_return = "status"\n', "lua: function.end: 'end' is a Lua keyword"),
        ):
            with self.subTest(message=message):
                self.assertIn(message, self.validate(text))

    def test_generated_names_are_reserved_for_parameters_only(self) -> None:
        for name in ("result", "type", "assert", "tonumber", "setmetatable", "self", "h"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(mutate(FIXTURE, 'unit = "u32"', f'{name} = "u32"')),
                    [f"lua: function.open_port.{name}: '{name}' is a name the generated code uses"],
                )
        self.assertEqual(self.validate(mutate(FIXTURE, "status", "result", every=True)), [])
        # spend has no class, so only M.raw reaches it
        self.assertEqual(self.validate(mutate(FIXTURE, 'htoken = "token"', 'result = "token"')), [])

    def test_constant_and_class_name_clash(self) -> None:
        text = mutate(FIXTURE, "max_units = 16", "io = 16")
        text = mutate(text, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_class = "i_o"')  # both M.IO
        self.assertEqual(
            self.validate(text),
            ["lua: module M: IO would be defined more than once, by untyped_const.io and opaque_ref.port._class"],
        )

    def test_member_collision(self) -> None:
        text = mutate(FIXTURE, 'generation = { _type = "u32", _ref = "out" }', 'send = { _type = "u32", _ref = "out" }')
        self.assertEqual(
            self.validate(text),
            ["lua: class Port: send would be defined more than once, by function.send and function.open_port.send"],
        )

    def test_class_collision(self) -> None:
        self.assertEqual(
            self.validate(mutate(KITCHEN_SINK, '_class = "data_link"', '_class = "port"')),
            ["lua: module M: Port would be defined more than once, by opaque_ref.port._class and opaque_ref.link._class"],
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
            ("status_to_string", "status_to_string would be defined more than once, by untyped_const[0]._to_string and typed_const.status._to_string"),
            ("feat_to_string", "feat_to_string would be defined more than once, by untyped_bit_const[0]._to_string and untyped_const[0]._to_string"),
            ("MAX_UNITS", "MAX_UNITS would be defined more than once, by untyped_const.max_units and untyped_const[0]._to_string"),
            ("raw", "raw would be defined more than once, by untyped_const[0]._to_string and the raw function table"),
            ("Port", "Port would be defined more than once, by untyped_const[0]._to_string and opaque_ref.port._class"),
        ):
            with self.subTest(name=name):
                text = mutate(FIXTURE, '_to_string = "limit_to_string"', f'_to_string = "{name}"')
                self.assertEqual(self.validate(text), [f"lua: module M: {message}"])



class GroupDocstring(unittest.TestCase):
    def test_a_function_groups_docstring_heads_its_first_function_in_cdef_raw_and_a_class(self) -> None:
        text = emit_binding_lua.emit(
            load(DOCUMENTED_FUNCTION_GROUPS),
            source_name="xy_api.adef.toml", name="xy_api", library="libxy.so", project="xy",
        )
        for expected in (
            "\n/* port lifecycle */\nxy_status xy_open_port(",
            "\n/* traffic */\n/* buf: bytes to send */\nxy_status xy_send(",
            "\n    -- port lifecycle\n    open_port = lib.xy_open_port,\n    destroy_port = lib.xy_destroy_port,\n"
            "    -- traffic\n    send = lib.xy_send,\n",
            "\n-- port lifecycle\nfunction M.Port.new(",
            "\n-- traffic\n-- buf: bytes to send\nfunction M.Port.send(",
            "\n-- release the port\nfunction M.Port.destroy_port(",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
