import tempfile
import unittest
from pathlib import Path

from api_gen import model, naming
from api_gen.tests.support import FIXTURE, KITCHEN_SINK, load, mutate


class ModelErrors(unittest.TestCase):
    def assert_error(self, text: str, fragment: str) -> None:
        with self.assertRaises(model.DefinitionError) as caught:
            load(text)
        self.assertIn(fragment, str(caught.exception))

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
        self.assert_error(mutate(FIXTURE, "[_general]\n", '[_general]\n_colour = "red"\n'),
                          "_general: unknown key(s) _colour")
        self.assert_error(mutate(FIXTURE, "[_driver_data]\n", '[_driver_data]\n_colour = "red"\n'),
                          "_driver_data: unknown key(s) _colour")

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

    def test_optional_needs_a_nullable_parameter(self) -> None:
        for text, message in (
            (mutate(FIXTURE, 'unit = "u32"', 'unit = { _type = "u32", _optional = true }'),
             "function.open_port.unit._optional: a by-value parameter has no null to pass"),
            (mutate(KITCHEN_SINK, 'hport = "port"\npdst = { _type = "memory", _ref = "out",',
                    'hport = "port"\npdst = { _type = "memory", _ref = "out", _optional = true,'),
             'function.recv.pdst._optional: a memory parameter is optional only with _ref = "in"'),
            (mutate(KITCHEN_SINK, 'data = { _type = "memory", _ref = "inout",', 'data = { _type = "memory", _ref = "inout", _optional = true,'),
             'function.bump.data._optional: a memory parameter is optional only with _ref = "in"'),
        ):
            with self.subTest(message=message):
                self.assert_error(text, message)
        memory_in = load(mutate(FIXTURE, '_ref = "in", _count = "u64"', '_ref = "in", _optional = true, _count = "u64"'))
        self.assertTrue(next(f for f in memory_in.functions if f.name == "send").params[1].optional)

    def test_return_enum_needs_zero(self) -> None:
        self.assert_error(mutate(FIXTURE, "ok = 0", "ok = 1"), "no zero-valued entry")

    def test_quoted_library_rejected(self) -> None:
        self.assert_error(mutate(FIXTURE, '_library = "libxy.so"', '_library = "lib\\"xy.so"'), "must not contain")
        self.assert_error(mutate(FIXTURE, '_header = "xy/', '_header = "xy\\\\'), "must not contain")

    def test_library_and_header_refuse_control_characters(self) -> None:
        for needle, replacement, where in (
            ('_library = "libxy.so"', '_library = "libxy.so\\n"', "_general._library"),
            ('_header = "xy/', '_header = "xy\\r/', "_driver_data._header"),
        ):
            with self.subTest(where=where):
                self.assert_error(mutate(FIXTURE, needle, replacement),
                                  f"{where} must not contain '\"', '\\' or a control character")

    def test_bit_index_fits_the_base_type(self) -> None:
        for base_type, top in (("i32", 30), ("u32", 31)):
            text = mutate(FIXTURE, "[[untyped_bit_const]]\n", f'[[untyped_bit_const]]\n_base_type = "{base_type}"\n')
            for index in (top + 1, -1):
                with self.subTest(base_type=base_type, index=index):
                    self.assert_error(
                        mutate(text, "_value = 3,", f"_value = {index},"),
                        f"untyped_bit_const.feat_b: bit index {index} is outside 0..{top} for _base_type {base_type}",
                    )
            value = next(c for c in load(mutate(text, "_value = 3,", f"_value = {top},")).bit_consts if c.name == "feat_b")
            self.assertEqual(value.value, 1 << top)

    def test_version_bytes_are_0_to_255(self) -> None:
        self.assertEqual(load(mutate(FIXTURE, "[1, 2, 3, 4]", "[255, 255, 255, 255]")).version_value(), 0xFFFFFFFF)
        for version in ("[256, 2, 3, 4]", "[1, 2, 3, -1]"):
            with self.subTest(version=version):
                self.assert_error(mutate(FIXTURE, "[1, 2, 3, 4]", version), "4 integers in 0..255")

    def test_docstring_terminators_rejected(self) -> None:
        for terminator in ("*/", "]]"):
            with self.subTest(terminator=terminator):
                self.assert_error(
                    mutate(FIXTURE, '_docstring = "wire magic"', f'_docstring = "wire {terminator} magic"'),
                    "untyped_const.magic._docstring must not contain '*/' or ']]'",
                )

    def test_general_has_no_name_field(self) -> None:
        self.assert_error(mutate(FIXTURE, "[_general]\n", '[_general]\nname = "xy_api"\n'), "_general: unknown key(s) name")

    def test_namespace_is_an_identifier(self) -> None:
        self.assert_error(mutate(FIXTURE, '_namespace = "xy"', '_namespace = "x-y"'),
                          "_general._namespace must be an identifier string")

    def test_struct_rules(self) -> None:
        for text, message in (
            (FIXTURE + '\n[struct.early]\nx = "late"\n\n[struct.late]\ny = "u32"\n',
             "struct.early.x: struct 'late' must be defined before it is used"),
            (mutate(FIXTURE, 'bytes = "u64"', 'bytes = "memory"'), "struct.stats.bytes: 'memory' is not a field type"),
            (FIXTURE + '\n[struct.empty]\n_docstring = "nothing"\n', "struct.empty: has no fields"),
        ):
            with self.subTest(message=message):
                self.assert_error(text, message)

    def test_typed_const_has_entries(self) -> None:
        self.assert_error(FIXTURE + '\n[typed_const.none]\n_docstring = "nothing"\n', "typed_const.none: has no entries")

    def test_driver_data_rules(self) -> None:
        for needle, replacement, message in (
            ('_header = "xy/driver/xy_ioctl.h"\n', "", "_driver_data._header must be a string"),
            ('feat_a = "XYD_FEAT_A"', 'feat_a = "XYD-FEAT-A"', "_driver_data.const_pins.feat_a: must be a driver macro name"),
            ('[_driver_data.const_pins]\nfeat_a = "XYD_FEAT_A"', "const_pins = 5", "_driver_data.const_pins must be a table"),
        ):
            with self.subTest(message=message):
                self.assert_error(mutate(FIXTURE, needle, replacement), message)

    def test_typed_const_fits_its_base_type(self) -> None:
        self.assert_error(mutate(FIXTURE, "ok = 0", "ok = 0x80000000"), "typed_const.status.ok: 2147483648 does not fit i32")
        u32 = mutate(FIXTURE, '_docstring = "call outcome"', '_base_type = "u32"')
        self.assert_error(mutate(u32, "err_busy = { _value = 9", "err_busy = { _value = -9"),
                          "typed_const.status.err_busy: -9 does not fit u32")
        # above the i32 maximum is the header's objection, not the loader's
        entries = load(mutate(u32, "0x7fffffff", "0xffffffff")).typed_consts[0].entries
        self.assertEqual(next(e for e in entries if e.name == "err_other").value, 2**32 - 1)

    def test_untyped_value_fits_its_group_base_type(self) -> None:
        for base_type, low, high in (("i32", -(2**31), 2**31 - 1), ("u32", 0, 2**32 - 1)):
            text = mutate(FIXTURE, "[[untyped_const]]\n", f'[[untyped_const]]\n_base_type = "{base_type}"\n')
            for bad in (low - 1, high + 1):
                with self.subTest(base_type=base_type, value=bad):
                    self.assert_error(mutate(text, "max_units = 16", f"max_units = {bad}"),
                                      f"untyped_const.max_units: {bad} does not fit {base_type} ({low}..{high})")
            for good in (low, high):
                with self.subTest(base_type=base_type, value=good):
                    self.assertEqual(load(mutate(text, "max_units = 16", f"max_units = {good}")).consts[0].value, good)

    def test_sum_and_its_literal_terms_fit_the_base_type(self) -> None:
        self.assert_error(mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbig = ["0x7fffffff", "max_units"]'),
                          "untyped_const.big: 2147483663 does not fit i32")
        self.assert_error(mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbig = ["0x80000000", "-1"]'),
                          "untyped_const.big: term 0x80000000: 2147483648 does not fit i32")
        self.assert_error(mutate(FIXTURE, '["feat_a", "feat_b"]', '["feat_a", "0x80000000"]'),
                          "untyped_bit_const.feat_ab: term 0x80000000: 2147483648 does not fit i32")

    def test_sum_terms_share_its_base_type(self) -> None:
        u32_bits = '\n[[untyped_bit_const]]\n_base_type = "u32"\nfeat_c = 0\n'
        self.assert_error(
            mutate(FIXTURE, "\n[[untyped_const]]", u32_bits + 'feat_x = ["feat_c", "feat_b"]\n\n[[untyped_const]]'),
            "untyped_bit_const.feat_x (u32) composes untyped_bit_const.feat_b (i32): a sum's terms share its _base_type",
        )
        u32_plain = '\n[[untyped_const]]\n_base_type = "u32"\nwire = ["max_units"]\n'
        self.assert_error(
            mutate(FIXTURE, "\n[[string_const]]", u32_plain + "\n[[string_const]]"),
            "untyped_const.wire (u32) composes untyped_const.max_units (i32): a sum's terms share its _base_type",
        )

    def test_sum_may_name_an_earlier_group_of_the_same_base_type(self) -> None:
        text = mutate(FIXTURE, "\n[[untyped_const]]", '\n[[untyped_bit_const]]\nfeat_x = ["feat_b", "1"]\n\n[[untyped_const]]')
        text = mutate(text, "\n[[string_const]]", '\n[[untyped_const]]\ntotal = ["max_units", "4"]\n\n[[string_const]]')
        api = load(text)
        self.assertEqual(next(c for c in api.bit_consts if c.name == "feat_x").value, 9)
        self.assertEqual(next(c for c in api.consts if c.name == "total").value, 20)

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

    def test_string_const_rejects_control_characters(self) -> None:
        for escape in ("\\n", "\\r", "\\t", "\\u0000", "\\u001b", "\\u007f"):
            with self.subTest(escape=escape):
                self.assert_error(
                    mutate(FIXTURE, 'product = "xy widget"', f'product = "xy{escape}widget"'),
                    "string_const.product: value must not contain '\"', '\\' or a control character",
                )

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
        self.assert_error(mutate(FIXTURE, 'product = "xy', '_product = "xy'), "string_const[0]: unknown key(s) _product")
        self.assert_error(mutate(FIXTURE, '_return = "status"\nunit', "unit"), "missing '_return'")

    def test_docstring_is_a_member_name(self) -> None:
        load(mutate(FIXTURE, "bytes = ", "docstring = "))

    def test_keywords_are_the_emitters_concern(self) -> None:
        load(mutate(FIXTURE, "bytes = ", "return = "))
        load(mutate(FIXTURE, 'unit = "u32"', 'result = "u32"'))

    def test_undecodable_definition_is_a_definition_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "xy_api.adef.toml"
            path.write_bytes(b'[_general]\n_namespace = "\xff"\n')  # deliberately not UTF-8
            with self.assertRaises(model.DefinitionError):
                model.load(path)

    def test_single_table_constants_are_rejected(self) -> None:
        for key in ("untyped_const", "untyped_bit_const", "string_const"):
            with self.subTest(key=key):
                self.assert_error(mutate(FIXTURE, f"[[{key}]]", f"[{key}]"), f"[{key}] must be an array of tables, [[{key}]]")

    def test_string_group_has_no_base_type(self) -> None:
        self.assert_error(
            mutate(FIXTURE, "[[string_const]]", '[[string_const]]\n_base_type = "u32"'),
            "string_const[0]: unknown key(s) _base_type",
        )

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
        self.assertEqual(load(mutate(FIXTURE, "[[untyped_const]]\n", u32)).const_groups[0].base_type, "u32")

    def test_float_constants_are_not_implemented(self) -> None:
        for text, message in (
            (mutate(FIXTURE, "max_units = 16", "max_units = 1.5"), "untyped_const.max_units: f64 constants are not implemented"),
            (mutate(FIXTURE, "[[untyped_const]]\n", '[[untyped_const]]\n_base_type = "f32"\n'),
             "untyped_const[0]._base_type: f32 constants are not implemented"),
        ):
            with self.subTest(message=message), self.assertRaises(model.NotImplementedDefinition) as caught:
                load(text)
            self.assertEqual(str(caught.exception), message)

    def test_float_bit_flags_and_enums_are_errors(self) -> None:
        for needle, replacement in (
            ("[[untyped_bit_const]]\n", '[[untyped_bit_const]]\n_base_type = "f64"\n'),
            ('_docstring = "call outcome"', '_base_type = "f64"'),
        ):
            with self.subTest(replacement=replacement):
                with self.assertRaises(model.DefinitionError) as caught:
                    load(mutate(FIXTURE, needle, replacement))
                self.assertNotIsInstance(caught.exception, model.NotImplementedDefinition)
                self.assertIn("_base_type must be one of i32, u32", str(caught.exception))

    def test_unknown_type(self) -> None:
        self.assert_error(mutate(FIXTURE, 'unit = "u32"', 'unit = "u128"'), "unknown type 'u128'")

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

    def test_bit_sum_refuses_overlapping_terms(self) -> None:
        self.assert_error(
            mutate(FIXTURE, '["feat_a", "feat_b"]', '["feat_a", "1"]'),
            "untyped_bit_const.feat_ab: feat_a and 1 share bits",
        )

    def test_composed_term_must_be_a_literal_or_known_entry(self) -> None:
        self.assert_error(
            mutate(FIXTURE, '["feat_a", "feat_b"]', '["feat_a", "bogus"]'),
            "untyped_bit_const.feat_ab: composes unknown constant 'bogus' (only earlier untyped_bit_const entries or literals)",
        )
        self.assert_error(
            mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbad = ["bogus"]'),
            "untyped_const.bad: composes unknown constant 'bogus' (only earlier untyped_const entries or literals)",
        )

    def test_literal_term_is_decimal_or_0x_hex_with_an_optional_minus(self) -> None:
        for term, value, fmt in (("4", 4, "dec"), ("-4", -4, "dec"), ("0x1f", 31, "hex"), ("0x1F", 31, "hex"),
                                 ("-0x3", -3, "hex"), ("0", 0, "dec")):
            with self.subTest(term=term):
                api = load(mutate(FIXTURE, "max_units = 16", f'max_units = 16\ntotal = ["max_units", "{term}"]'))
                total = next(c for c in api.consts if c.name == "total")
                self.assertEqual(total.parts, ("max_units", model.LiteralTerm(value, fmt)))
                self.assertEqual(total.value, 16 + value)
        for term in ("0o17", "0b11", "1_000", "+5", " 5", "5 ", "0X1F", "0x", "-", "--1", "1e3"):
            with self.subTest(term=term):
                self.assert_error(
                    mutate(FIXTURE, "max_units = 16", f'max_units = 16\ntotal = ["max_units", "{term}"]'),
                    f"untyped_const.total: term '{term}' is neither an entry name nor a literal",
                )

    def test_plain_group_composes_by_addition(self) -> None:
        api = load(mutate(FIXTURE, "max_units = 16", 'max_units = 16\ntotal = ["max_units", "4"]'))
        self.assertEqual(next(c for c in api.consts if c.name == "total").value, 20)

    def test_composed_entry_dict_form_equals_naked_list(self) -> None:
        api = load(KITCHEN_SINK)
        naked = mutate(KITCHEN_SINK, 'feat_lit = { _value = ["feat_a", "4"] }', 'feat_lit = ["feat_a", "4"]')
        self.assertEqual(load(naked), api)

    def test_memory_needs_a_ref(self) -> None:
        self.assert_error(mutate(FIXTURE, '_ref = "in", ', ""), "function.send.buf: a 'memory' parameter needs _ref")

    def test_memory_count(self) -> None:
        self.assert_error(mutate(FIXTURE, '_count = "u64", ', ""),
                          "function.send.buf: a 'memory' parameter requires _count, one of u8, u16, u32, u64")
        self.assert_error(mutate(FIXTURE, '_count = "u64"', '_count = "port"'), "requires _count, one of u8, u16, u32, u64")
        self.assert_error(mutate(FIXTURE, '_count = "u64"', '_count = "i64"'), "requires _count, one of u8, u16, u32, u64")
        self.assert_error(mutate(FIXTURE, '_count = "u64"', '_count = "f64"'), "requires _count, one of u8, u16, u32, u64")
        self.assert_error(mutate(FIXTURE, 'unit = "u32"', 'unit = { _type = "u32", _count = "u32" }'),
                          "function.open_port.unit._count: only a 'memory' parameter has a count")
        self.assert_error(mutate(FIXTURE, 'hport = "port"\nbuf', 'buf_count = "u32"\nbuf'),
                          "function.send.buf: its count parameter buf_count is already a parameter")
        self.assertEqual(load().functions[2].params[1].count_type, "u64")

    def test_missing_general(self) -> None:
        self.assert_error("[function]\n", "missing [_general] table")

    def test_unknown_format(self) -> None:
        self.assert_error(mutate(FIXTURE, '_format = "hex" }\n\n[opaque', '_format = "oct" }\n\n[opaque'), "_format must be one of")

    def test_ctor_needs_one_out_of_the_opaque(self) -> None:
        self.assert_error(mutate(FIXTURE, '_ctor = "open_port"', '_ctor = "send"'), "exactly one port parameter of _ref \"out\"")

    def test_ctor_and_dtor_are_function_names(self) -> None:
        for key in ("_ctor", "_dtor"):
            with self.subTest(key=key):
                self.assert_error(mutate(FIXTURE, f'{key} = "', f'{key} = 5 # "'), f"opaque_ref.port.{key} must be a function name")

    def test_dtor_takes_only_the_opaque(self) -> None:
        for dtor in ("send", "nope"):
            with self.subTest(dtor=dtor):
                self.assert_error(mutate(FIXTURE, '_dtor = "destroy_port"', f'_dtor = "{dtor}"'),
                                  f"opaque_ref.port._dtor: '{dtor}' must name a function whose only parameter is a port by value")

    def test_dtor_requires_ctor(self) -> None:
        self.assert_error(mutate(FIXTURE, '_ctor = "open_port"\n', ""), "_dtor: requires _ctor")

    def test_string_const_rejects_a_quote(self) -> None:
        self.assert_error(mutate(FIXTURE, 'product = "xy widget"', "product = 'xy \"widget\"'"), "string_const.product")

    def test_plain_and_string_constants_share_the_constant_namespace(self) -> None:
        self.assert_error(mutate(FIXTURE, "max_units = 16", "ok = 16"), "XY_OK already defined")
        self.assert_error(mutate(FIXTURE, 'product = "xy widget"', 'max_units = "x"'), "XY_MAX_UNITS already defined")

    def test_to_string_is_a_name(self) -> None:
        for needle, value, message in (
            ('_to_string = "to_string"', '"_x"', "typed_const.status._to_string: '_x': a key beginning with '_' is a property"),
            ('_to_string = "to_string"', "5", "typed_const.status._to_string must be an identifier"),
            ('_to_string = "feat_to_string"', '"9x"', "untyped_bit_const[0]._to_string: '9x' is not an identifier"),
            ('_to_string = "limit_to_string"', '"a-b"', "untyped_const[0]._to_string: 'a-b' is not an identifier"),
        ):
            with self.subTest(message=message):
                self.assert_error(mutate(FIXTURE, needle, f"_to_string = {value}"), message)

    def test_string_group_has_no_to_string(self) -> None:
        self.assert_error(
            mutate(FIXTURE, "[[string_const]]\n", '[[string_const]]\n_to_string = "product_to_string"\n'),
            "string_const[0]: unknown key(s) _to_string",
        )

    def test_class_must_be_an_identifier(self) -> None:
        self.assert_error(mutate(FIXTURE, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_class = "a-b"'),
                          "_class must be an identifier")

    def test_class_is_lowercase(self) -> None:
        self.assert_error(mutate(FIXTURE, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_class = "DataLink"'),
                          "opaque_ref.port._class: 'DataLink' must be lowercase; each binding applies its own casing")
        self.assertEqual(load(mutate(FIXTURE, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_class = "link_2"'))
                         .opaque_refs[0].class_name, "link_2")

    def test_classes_whose_casing_collides_are_the_bindings_concern(self) -> None:
        load(mutate(KITCHEN_SINK, '_class = "data_link"', '_class = "port"'))


class Naming(unittest.TestCase):
    def test_every_spec_naming_row(self) -> None:
        self.assertEqual(naming.const_name("tcdl", "cap_compute"), "TCDL_CAP_COMPUTE")
        self.assertEqual(naming.const_name("tcdl", "ok"), "TCDL_OK")
        self.assertEqual(naming.type_name("tcdl", "result"), "tcdl_result")
        self.assertEqual(naming.function_name("tcdl", "create_device"), "tcdl_create_device")
        self.assertEqual(naming.opaque_struct("tcdl", "handle"), "tcdl_handle_opaque")
        self.assertEqual(naming.version_const("tcdl"), "TCDL_API_VERSION")
        self.assertEqual(naming.api_macro("tcdl"), "TCDL_API")
        self.assertEqual(naming.unprefixed_const_name("err_no_device"), "ERR_NO_DEVICE")
        self.assertEqual(naming.upper_camel("my_ns"), "MyNs")
        self.assertEqual(naming.c_api_macro("tcdl"), "TCDL_C_API")
        self.assertEqual(naming.impl_macro("tcdl"), "TCDL_IMPL")
        self.assertEqual(naming.count_param("psrc"), "psrc_count")
        self.assertEqual(naming.lua_to_string("to_string", typename="result"), "result_to_string")
        self.assertEqual(naming.lua_to_string("cap_to_string", typename=None), "cap_to_string")
        self.assertEqual(naming.unknown_value_name("result"), "UNKNOWN_RESULT")
        self.assertEqual(naming.unknown_value_name(None), "UNKNOWN")


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
            [(g.docstring, g.base_type, [c.name for c in g.entries]) for g in api.bit_const_groups],
            [
                ("feature flags", "i32", ["feat_a", "feat_b", "feat_ab", "feat_lit"]),
                (None, "u32", ["feat_one", "feat_all"]),
                ("access flags", "i32", ["acc_a", "acc_b", "acc_ab"]),
            ],
        )
        self.assertEqual(
            [(g.docstring, g.base_type, [c.name for c in g.entries]) for g in api.const_groups],
            [
                ("limits", "i32", ["max_units", "extra", "max_total", "neg", "low", "floor", "dip"]),
                ("wire values", "u32", ["magic"]),
            ],
        )
        self.assertEqual(
            [c.name for c in api.bit_consts],
            ["feat_a", "feat_b", "feat_ab", "feat_lit", "feat_one", "feat_all", "acc_a", "acc_b", "acc_ab"],
        )
        self.assertEqual(
            [c.name for c in api.consts], ["max_units", "extra", "max_total", "neg", "low", "floor", "dip", "magic"]
        )
        self.assertEqual(
            next(c for c in api.bit_consts if c.name == "feat_all").parts, ("feat_one", model.LiteralTerm(8, "dec"))
        )
        self.assertEqual({t.name: t.base_type for t in api.typed_consts}, {"status": "i32", "mode": "u32"})
        self.assertEqual(
            [(g.docstring, [c.name for c in g.entries]) for g in api.string_const_groups],
            [(None, ["product", "vendor"])],
        )
        self.assertEqual([c.name for c in api.string_consts], ["product", "vendor"])

    def test_composed_values_sum(self) -> None:
        api = load(KITCHEN_SINK)
        by_name = {c.name: c.value for c in api.bit_consts}
        self.assertEqual(by_name["feat_ab"], 9)
        self.assertEqual(by_name["feat_lit"], 5)
        self.assertEqual(by_name["feat_all"], 9)
        plain = {c.name: c.value for c in api.consts}
        self.assertEqual(plain["max_total"], 20)

    def test_to_string_loads_on_typed_bit_and_plain_groups(self) -> None:
        api = load()
        self.assertEqual(
            (api.typed_consts[0].to_string, api.bit_const_groups[0].to_string, api.const_groups[0].to_string),
            ("to_string", "feat_to_string", "limit_to_string"),
        )

    def test_to_string_absent_is_none(self) -> None:
        api = load(KITCHEN_SINK)
        self.assertEqual([g.to_string for g in api.bit_const_groups], [None, None, "access_to_string"])
        self.assertEqual([g.to_string for g in api.const_groups], ["limit_to_string", None])
        self.assertEqual([g.to_string for g in api.string_const_groups], [None])
        typed = load(mutate(FIXTURE, '_to_string = "to_string"\n', "")).typed_consts[0]
        self.assertIsNone(typed.to_string)

    def test_names_include_to_string(self) -> None:
        names = load().names()
        for pair in (
            ("typed_const.status._to_string", "to_string"),
            ("untyped_bit_const[0]._to_string", "feat_to_string"),
            ("untyped_const[0]._to_string", "limit_to_string"),
        ):
            self.assertIn(pair, names)

    def test_single_bit_entries_exclude_composed_multi_bit_ones(self) -> None:
        groups = load(KITCHEN_SINK).bit_const_groups
        self.assertEqual([c.name for c in model.single_bit_entries(groups[0])], ["feat_a", "feat_b"])
        self.assertEqual([c.name for c in model.single_bit_entries(groups[1])], ["feat_one"])

    def test_version_value(self) -> None:
        self.assertEqual(load().version_value(), 0x01020304)

    def test_classes_are_the_opaque_refs_with_a_ctor_as_the_definition_states_them(self) -> None:
        api = load(KITCHEN_SINK)
        self.assertEqual(
            [
                (c.opaque.name, c.ctor.name, c.handle.name, [p.name for p in c.cached], [f.name for f in c.methods],
                 c.dtor and c.dtor.name)
                for c in api.classes()
            ],
            [
                ("port", "open_port", "pport", ["pstats", "generation", "pwrap"],
                 ["send", "recv", "configure", "stats_of", "bump", "annotate", "seek", "tune", "probe"], "destroy_port"),
                ("link", "open_link", "plink", [], [], None),
            ],
        )

    def test_success_entry_is_the_zero_valued_one(self) -> None:
        text = mutate(FIXTURE, "ok = 0\nerr_busy = { _value = 9", "err_busy = { _value = 9")
        api = load(mutate(text, 'err_other = { _value = 0x7fffffff, _format = "hex" }',
                          'err_other = { _value = 0x7fffffff, _format = "hex" }\nfine = 0'))
        self.assertEqual(api.success_entry(api.functions[0]).name, "fine")

    def test_names_list_every_constant_once(self) -> None:
        api = load(KITCHEN_SINK)
        constants = api.constant_names()
        self.assertEqual(len(constants), len({name for _, name in constants}))
        self.assertTrue(set(constants) <= set(api.names()))
        self.assertEqual(
            api.constant_names(enum_entries=False), [pair for pair in constants if not pair[0].startswith("typed_const.")]
        )


if __name__ == "__main__":
    unittest.main()
