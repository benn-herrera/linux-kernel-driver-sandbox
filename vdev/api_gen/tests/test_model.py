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

    def test_unknown_top_level_table(self) -> None:
        self.assert_error(mutate(FIXTURE, "[opaque_ref.token]", "[opque_ref.token]"), "unknown table(s) [opque_ref]")

    def test_entry_attributes_begin_with_underscore(self) -> None:
        for needle, plain, where in (
            ('_value = 9, _docstring = "try later"', "value", "typed_const.status.err_busy"),
            ('_type = "u32", _docstring = "items seen"', "type", "struct.stats.count"),
            ('_type = "stats", _ref = "out", _optional', "type", "function.open_port.pstats"),
            ('_value = "acme"', "value", "string_const.vendor"),
        ):
            with self.subTest(where=where):
                text = mutate(FIXTURE, needle, needle.replace(f"_{plain} = ", f"{plain} = ", 1))
                self.assert_error(text, f"{where}: '{plain}': entry attributes begin with _")

    def test_unknown_underscore_attribute_names_key_and_context(self) -> None:
        self.assert_error(mutate(FIXTURE, '_value = 3,', '_value = 3, _colour = "red",'),
                          "untyped_bit_const.feat_b: unknown key(s) _colour")
        self.assert_error(mutate(FIXTURE, '_ref = "in", ', '_ref = "in", _size = "len", '),
                          "function.send.buf: unknown key(s) _size")
        self.assert_error(mutate(FIXTURE, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_colour = "red"'),
                          "opaque_ref.port: unknown key(s) _colour")

    def test_opaque_ref_has_only_properties(self) -> None:
        self.assert_error(mutate(FIXTURE, '_ctor = "open_port"', 'ctor = "open_port"'),
                          "opaque_ref.port: 'ctor': an opaque_ref has no members")

    def test_naked_values_are_sugar_and_nested_tables_equal_inline_ones(self) -> None:
        api = load()
        for needle, spelled_out in (
            ("ok = 0", "ok = { _value = 0 }"),
            ("feat_a = 0", "feat_a = { _value = 0 }"),
            ('product = "xy widget"', 'product = { _value = "xy widget" }'),
            ('bytes = "u64"', 'bytes = { _type = "u64" }'),
            ('unit = "u32"', 'unit = { _type = "u32" }'),
            ('hport = "port"\nbuf', 'hport = { _type = "port" }\nbuf'),
            ('err_other = { _value = 0x7fffffff, _format = "hex" }',
             '[typed_const.status.err_other]\n_value = 0x7fffffff\n_format = "hex"'),
            ('[opaque_ref.port]\n_ctor = "open_port"\n_dtor = "destroy_port"',
             '[opaque_ref]\nport = { _ctor = "open_port", _dtor = "destroy_port" }'),
        ):
            with self.subTest(needle=needle):
                self.assertEqual(load(mutate(FIXTURE, needle, spelled_out)), api)

    def test_ref_values(self) -> None:
        self.assert_error(mutate(FIXTURE, '_ref = "in"', '_ref = "both"'), "function.send.buf._ref must be one of in, out, inout")
        self.assertEqual(
            [p.ref for p in load().functions[0].params], [None, "out", "out", "out"]
        )

    def test_optional_is_a_boolean(self) -> None:
        self.assert_error(mutate(FIXTURE, "_optional = true", '_optional = "yes"'), "_optional must be true or false")
        self.assertTrue(load().functions[0].params[2].optional)

    def test_return_enum_needs_zero(self) -> None:
        self.assert_error(mutate(FIXTURE, "ok = 0", "ok = 1"), "no zero-valued entry")

    def test_quoted_library_rejected(self) -> None:
        self.assert_error(mutate(FIXTURE, '_library = "libxy.so"', '_library = "lib\\"xy.so"'), "must not contain")
        self.assert_error(mutate(FIXTURE, '_header = "xy/', '_header = "xy\\\\'), "must not contain")

    def test_bit_index_range(self) -> None:
        self.assert_error(mutate(FIXTURE, "_value = 3,", "_value = 31,"), "bit index must be 0..30")
        load(mutate(FIXTURE, "_value = 3,", "_value = 30,"))

    def test_version_first_byte_range(self) -> None:
        self.assert_error(mutate(FIXTURE, "[1, 2, 3, 4]", "[128, 2, 3, 4]"), "first byte must be 0..127")
        load(mutate(FIXTURE, "[1, 2, 3, 4]", "[127, 2, 3, 4]"))

    def test_docstring_terminators_rejected(self) -> None:
        self.assert_error(mutate(FIXTURE, '_docstring = "wire magic"', '_docstring = "wire */ magic"'), "must not contain")

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

    def test_ctor_cannot_cache_a_memory_out(self) -> None:
        self.assert_error(
            mutate(FIXTURE,
                'generation = { _type = "u32", _ref = "out" }',
                'generation = { _type = "u32", _ref = "out" }\nblob = { _type = "memory", _ref = "out", _count = "u32" }',
            ),
            "a constructor cannot cache a memory out parameter",
        )

    def test_ctor_has_no_inout_parameter(self) -> None:
        self.assert_error(
            mutate(FIXTURE, 'generation = { _type = "u32", _ref = "out" }', 'generation = { _type = "u32", _ref = "inout" }'),
            "function.open_port.generation: a constructor has no inout parameter",
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

    def test_memory_needs_a_ref(self) -> None:
        self.assert_error(mutate(FIXTURE, '_ref = "in", ', ""), "function.send.buf: a 'memory' parameter needs _ref")

    def test_memory_count(self) -> None:
        self.assert_error(mutate(FIXTURE, '_count = "u64", ', ""),
                          "function.send.buf: a 'memory' parameter requires _count, one of u32, u64")
        self.assert_error(mutate(FIXTURE, '_count = "u64"', '_count = "port"'), "requires _count, one of u32, u64")
        self.assert_error(mutate(FIXTURE, 'unit = "u32"', 'unit = { _type = "u32", _count = "u32" }'),
                          "function.open_port.unit._count: only a 'memory' parameter has a count")
        self.assert_error(mutate(FIXTURE, 'hport = "port"\nbuf', 'buf_count = "u32"\nbuf'),
                          "function.send.buf: its count parameter buf_count is already a parameter")
        self.assertEqual(load().functions[2].params[1].count_type, "u64")

    def test_missing_general(self) -> None:
        self.assert_error("[function]\n", "missing [_general] table")

    def test_general_name_is_rejected(self) -> None:
        self.assert_error(mutate(FIXTURE, "[_general]\n", '[_general]\nname = "xy_api"\n'), "file name is the output stem")

    def test_old_root_table_spellings_are_unknown(self) -> None:
        self.assert_error(mutate(FIXTURE, "[_general]", "[general]"), "unknown table(s) [general]")
        self.assert_error(mutate(FIXTURE, "[_driver_data]", "[driver_data]"), "unknown table(s) [driver_data]")

    def test_old_general_key_spellings_are_unknown(self) -> None:
        self.assert_error(mutate(FIXTURE, "_namespace = ", "namespace = "), "_general: unknown key(s) namespace")
        self.assert_error(mutate(FIXTURE, "_version = ", "version = "), "_general: unknown key(s) version")
        self.assert_error(mutate(FIXTURE, "_library = ", "library = "), "_general: unknown key(s) library")

    def test_old_driver_data_key_spelling_is_unknown(self) -> None:
        self.assert_error(mutate(FIXTURE, "_header = ", "header = "), "_driver_data: unknown key(s) header")

    def test_unknown_format(self) -> None:
        self.assert_error(mutate(FIXTURE, '_format = "hex" }\n\n[opaque', '_format = "oct" }\n\n[opaque'), "_format must be one of")

    def test_ctor_needs_one_out_of_the_opaque(self) -> None:
        self.assert_error(mutate(FIXTURE, '_ctor = "open_port"', '_ctor = "send"'), "exactly one port parameter of _ref \"out\"")

    def test_dtor_takes_only_the_opaque(self) -> None:
        self.assert_error(mutate(FIXTURE, '_dtor = "destroy_port"', '_dtor = "send"'), "only parameter is a port")

    def test_dtor_requires_ctor(self) -> None:
        self.assert_error(mutate(FIXTURE, '_ctor = "open_port"\n', ""), "_dtor: requires _ctor")

    def test_string_const_rejects_a_quote(self) -> None:
        self.assert_error(mutate(FIXTURE, 'product = "xy widget"', "product = 'xy \"widget\"'"), "string_const.product")

    def test_plain_and_string_constants_share_the_constant_namespace(self) -> None:
        self.assert_error(mutate(FIXTURE, "max_units = 16", "ok = 16"), "XY_OK already defined")
        self.assert_error(mutate(FIXTURE, 'product = "xy widget"', 'max_units = "x"'), "XY_MAX_UNITS already defined")

    def test_class_must_be_an_identifier(self) -> None:
        self.assert_error(mutate(FIXTURE, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_class = "a-b"'),
                          "_class must be an identifier")


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
