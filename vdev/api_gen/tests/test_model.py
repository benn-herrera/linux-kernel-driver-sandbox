import unittest

from api_gen import model, naming
from api_gen.tests.support import FIXTURE, KITCHEN_SINK, load, mutate


class ModelErrors(unittest.TestCase):
    def assert_error(self, text: str, fragment: str) -> None:
        with self.assertRaises(model.DefinitionError) as caught:
            load(text)
        self.assertIn(fragment, str(caught.exception))

    def test_keyword_as_name(self) -> None:
        for text in (
            mutate(FIXTURE, "bytes = ", "end = "),
            mutate(FIXTURE, 'unit = "u32"', 'int = "u32"'),
            FIXTURE + '\n[function.end]\n_return = "status"\n',
        ):
            self.assert_error(text, "keyword or a name")

    def test_cpp_keyword_as_name(self) -> None:
        for text in (
            mutate(FIXTURE, "unit = ", "class = "),
            mutate(FIXTURE, "count = ", "template = "),
            FIXTURE + '\n[function.new]\n_return = "status"\n',
        ):
            self.assert_error(text, "keyword")

    def test_generated_locals_reserved_for_parameters_only(self) -> None:
        self.assert_error(mutate(FIXTURE, 'unit = "u32"', 'result = "u32"'), "keyword or a name")
        load(mutate(FIXTURE, "status", "result"))

    def test_function_named_like_a_type(self) -> None:
        self.assert_error(FIXTURE + '\n[function.stats]\n_return = "status"\n', "already defined by struct.stats")

    def test_struct_named_like_an_opaque_tag(self) -> None:
        self.assert_error(FIXTURE + '\n[struct.port_opaque]\nx = "u32"\n', "already defined by opaque_ref.port")

    def test_memory_needs_size(self) -> None:
        self.assert_error(mutate(FIXTURE, ', size = "len"', ""), "names its 'size' parameter")

    def test_size_serves_one_buffer(self) -> None:
        text = mutate(FIXTURE, 'len = "u64"', 'len = "u64"\nbuf2 = { type = "memory", outref = true, size = "len" }')
        self.assert_error(text, "already the size of 'buf'")

    def test_return_enum_needs_zero(self) -> None:
        self.assert_error(mutate(FIXTURE, "ok = 0", "ok = 1"), "no zero-valued entry")

    def test_quoted_library_rejected(self) -> None:
        self.assert_error(mutate(FIXTURE, 'library = "libxy.so"', 'library = "lib\\"xy.so"'), "must not contain")
        self.assert_error(mutate(FIXTURE, 'header = "xy/', 'header = "xy\\\\'), "must not contain")

    def test_bit_index_range(self) -> None:
        self.assert_error(mutate(FIXTURE, "value = 3,", "value = 31,"), "bit index must be 0..30")
        load(mutate(FIXTURE, "value = 3,", "value = 30,"))

    def test_version_first_byte_range(self) -> None:
        self.assert_error(mutate(FIXTURE, "[1, 2, 3, 4]", "[128, 2, 3, 4]"), "first byte must be 0..127")
        load(mutate(FIXTURE, "[1, 2, 3, 4]", "[127, 2, 3, 4]"))

    def test_docstring_terminators_rejected(self) -> None:
        self.assert_error(mutate(FIXTURE, 'docstring = "wire magic"', 'docstring = "wire */ magic"'), "must not contain")

    def test_int32_range(self) -> None:
        self.assert_error(mutate(FIXTURE, "ok = 0", "ok = 0x80000000"), "int32 range")

    def test_builtin_shadow(self) -> None:
        self.assert_error(FIXTURE + '\n[struct.u32]\nx = "u64"\n', "shadows builtin")

    def test_constant_uniqueness(self) -> None:
        self.assert_error(
            mutate(FIXTURE, "feat_a = 0\n", "feat_a = 0\napi_version = 5\n"),
            "already defined by the API version constant",
        )
        self.assert_error(
            mutate(FIXTURE, "ok = 0\n", "ok = 0\nfeat_a = 4\n"),
            "already defined by untyped_bit_const.feat_a",
        )

    def test_string_const_rejects_newline(self) -> None:
        self.assert_error(mutate(FIXTURE, 'product = "xy widget"', 'product = "xy\\nwidget"'), "newline")

    def test_ctor_cannot_cache_a_memory_outref(self) -> None:
        self.assert_error(
            mutate(FIXTURE, 
                'generation = { type = "u32", outref = true }',
                'generation = { type = "u32", outref = true }\n'
                'blob = { type = "memory", outref = true, size = "unit" }',
            ),
            "a constructor cannot cache a memory outref",
        )

    def test_underscore_keys_are_properties_not_members(self) -> None:
        self.assert_error(mutate(FIXTURE, "bytes = ", "_bytes = "), "struct.stats: unknown key(s) _bytes")
        self.assert_error(mutate(FIXTURE, "max_units = ", "_max_units = "), "untyped_const[0]: unknown key(s) _max_units")
        self.assert_error(mutate(FIXTURE, "unit = ", "_unit = "), "function.open_port: unknown key(s) _unit")
        self.assert_error(mutate(FIXTURE, "ok = 0", "_ok = 0"), "typed_const.status: unknown key(s) _ok")
        self.assert_error(mutate(FIXTURE, 'product = "xy', '_product = "xy'), "is a property, not a name")
        self.assert_error(mutate(FIXTURE, '_return = "status"\nunit', "unit"), "missing '_return'")

    def test_docstring_is_a_member_name_and_return_a_keyword(self) -> None:
        load(mutate(FIXTURE, "bytes = ", "docstring = "))
        self.assert_error(mutate(FIXTURE, "bytes = ", "return = "), "keyword")

    def test_single_table_constants_are_rejected(self) -> None:
        for key in ("untyped_const", "untyped_bit_const"):
            with self.subTest(key=key):
                self.assert_error(mutate(FIXTURE, f"[[{key}]]", f"[{key}]"), f"[{key}] is now an array of tables")

    def test_empty_group_is_rejected(self) -> None:
        text = mutate(FIXTURE, "[[untyped_const]]\n", '[[untyped_const]]\n_docstring = "none"\n\n[[untyped_const]]\n')
        self.assert_error(text, "untyped_const[0]: has no entries")

    def test_base_type(self) -> None:
        self.assert_error(
            mutate(FIXTURE, "[[untyped_const]]\n", '[[untyped_const]]\n_base_type = "u64"\n'),
            "untyped_const[0]._base_type must be one of i32, u32",
        )
        self.assert_error(
            mutate(FIXTURE, '_docstring = "call outcome"', '_base_type = "int"'), "typed_const.status._base_type"
        )
        u32 = '[[untyped_const]]\n_base_type = "u32"\n'
        self.assert_error(mutate(FIXTURE, "[[untyped_const]]\nmax_units = 16", u32 + "max_units = -16"), "must not be negative")
        self.assert_error(mutate(FIXTURE, "[[untyped_const]]\nmax_units = 16", u32 + "max_units = 0x80000000"), "int32 range")
        self.assertEqual(load(mutate(FIXTURE, "[[untyped_const]]\n", u32)).const_groups[0].base_type, "u32")

    def test_unknown_type(self) -> None:
        self.assert_error(mutate(FIXTURE, 'unit = "u32"', 'unit = "u16"'), "unknown type 'u16'")

    def test_unknown_return_type(self) -> None:
        self.assert_error(mutate(FIXTURE, '_docstring = "release the port"\n_return = "status"',
                                          '_return = "nope"'), "unknown typed_const 'nope'")

    def test_duplicate_type_name_across_categories(self) -> None:
        self.assert_error(FIXTURE + "\n[opaque_ref.stats]\n", "already defined in")

    def test_pin_names_undefined_constant(self) -> None:
        self.assert_error(FIXTURE + 'feat_z = "XY_FEAT_Z"\n', "undefined untyped_bit_const 'feat_z'")

    def test_composed_constant_must_be_earlier(self) -> None:
        text = mutate(FIXTURE, '["feat_a", "feat_b"]', '["feat_a", "feat_c"]')
        self.assert_error(text, "unknown constant 'feat_c'")

    def test_size_must_name_a_sibling_integer(self) -> None:
        self.assert_error(mutate(FIXTURE, 'size = "len"', 'size = "hport"'), "must name a u32 or u64")

    def test_memory_needs_direction(self) -> None:
        self.assert_error(mutate(FIXTURE, "inref = true, ", ""), "must be inref or outref")

    def test_missing_general(self) -> None:
        self.assert_error("[function]\n", "missing [general] table")

    def test_general_name_is_rejected(self) -> None:
        self.assert_error(mutate(FIXTURE, "[general]\n", '[general]\nname = "xy_api"\n'), "file name is the output stem")

    def test_unknown_format(self) -> None:
        self.assert_error(mutate(FIXTURE, 'format = "hex" }\n\n[opaque', 'format = "oct" }\n\n[opaque'), "format must be one of")

    def test_ctor_needs_one_outref_of_the_opaque(self) -> None:
        self.assert_error(mutate(FIXTURE, 'ctor = "open_port"', 'ctor = "send"'), "exactly one port outref")

    def test_dtor_takes_only_the_opaque(self) -> None:
        self.assert_error(mutate(FIXTURE, 'dtor = "destroy_port"', 'dtor = "send"'), "only parameter is a port")

    def test_dtor_requires_ctor(self) -> None:
        self.assert_error(mutate(FIXTURE, 'ctor = "open_port"\n', ""), "dtor: requires ctor")

    def test_string_const_rejects_a_quote(self) -> None:
        self.assert_error(mutate(FIXTURE, 'product = "xy widget"', "product = 'xy \"widget\"'"), "string_const.product")

    def test_plain_and_string_constants_share_the_constant_namespace(self) -> None:
        self.assert_error(mutate(FIXTURE, "max_units = 16", "ok = 16"), "XY_OK already defined")
        self.assert_error(mutate(FIXTURE, 'product = "xy widget"', 'max_units = "x"'), "XY_MAX_UNITS already defined")

    def test_class_must_be_an_identifier(self) -> None:
        self.assert_error(mutate(FIXTURE, 'dtor = "destroy_port"', 'dtor = "destroy_port"\nclass = "a-b"'),
                          "class must be an identifier")


class Naming(unittest.TestCase):
    def test_every_spec_naming_row(self) -> None:
        self.assertEqual(naming.const_name("tcdl", "cap_compute"), "TCDL_CAP_COMPUTE")
        self.assertEqual(naming.const_name("tcdl", "ok"), "TCDL_OK")
        self.assertEqual(naming.type_name("tcdl", "result"), "tcdl_result")
        self.assertEqual(naming.function_name("tcdl", "create_device"), "tcdl_create_device")
        self.assertEqual(naming.opaque_struct("tcdl", "handle"), "tcdl_handle_opaque")
        self.assertEqual(naming.version_const("tcdl"), "TCDL_API_VERSION")
        self.assertEqual(naming.api_macro("tcdl"), "TCDL_API")
        self.assertEqual(naming.lua_const_name("err_no_device"), "ERR_NO_DEVICE")
        self.assertEqual(naming.upper_camel("my_ns"), "MyNs")


class Shape(unittest.TestCase):
    def test_parameter_order_is_document_order(self) -> None:
        fn = next(f for f in load().functions if f.name == "open_port")
        self.assertEqual([p.name for p in fn.params], ["unit", "pport", "pstats", "generation"])

    def test_class_defaults_to_the_name(self) -> None:
        port = next(o for o in load().opaque_refs if o.name == "port")
        self.assertEqual(port.class_name, "port")

    def test_groups_in_document_order_and_flat_accessors_span_them(self) -> None:
        api = load(KITCHEN_SINK)
        self.assertEqual(
            [(g.docstring, g.base_type, [c.key for c in g.entries]) for g in api.bit_const_groups],
            [("feature flags", "i32", ["feat_a", "feat_b", "feat_ab"]), (None, "u32", ["feat_all"])],
        )
        self.assertEqual(
            [(g.docstring, g.base_type, [c.key for c in g.entries]) for g in api.const_groups],
            [("limits", "i32", ["max_units", "neg"]), ("wire values", "u32", ["magic"])],
        )
        self.assertEqual([c.key for c in api.bit_consts], ["feat_a", "feat_b", "feat_ab", "feat_all"])
        self.assertEqual([c.key for c in api.consts], ["max_units", "neg", "magic"])
        self.assertEqual(api.bit_consts[-1].parts, ("feat_ab",))
        self.assertEqual({t.name: t.base_type for t in api.typed_consts}, {"status": "i32", "mode": "u32"})

    def test_version_value(self) -> None:
        self.assertEqual(load().version_value(), 0x01020304)


if __name__ == "__main__":
    unittest.main()
