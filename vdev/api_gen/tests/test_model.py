import tempfile
import unittest
from pathlib import Path

from api_gen import model
from api_gen.tests.support import (
    FIXTURE, KITCHEN_SINK, MINIMAL, NO_WRAPPED_API, TWO_BAD_RETURNS, assert_objection, load, mutate, objections,
)

# What FIXTURE's references to an item that failed report after the item's own objection:
# every function's `_return` names status, three parameters name port, one names stats and
# the pin names feat_a.
STATUS_REFS = [f"function.{f}._return: unknown typed_const 'status'" for f in ("open_port", "destroy_port", "send", "spend")]
PORT_REFS = [f"function.{p}: unknown type 'port'" for p in ("open_port.pport", "destroy_port.hport", "send.hport")]
STATS_REFS = ["function.open_port.pstats: unknown type 'stats'"]
FEAT_A_REFS = ["_wrapped_api._pinned_value.feat_a: pins undefined untyped_bit_const 'feat_a'"]
I32 = "i32 (-2147483648..2147483647)"


class ModelErrors(unittest.TestCase):
    def test_function_named_like_a_type(self) -> None:
        assert_objection(self, FIXTURE + '\n[function.stats]\n_return = "status"\n',
                         "function.stats: C identifier xy_stats already defined by struct.stats")

    def test_struct_named_like_an_opaque_tag(self) -> None:
        assert_objection(self, FIXTURE + '\n[struct.port_opaque]\nx = "u32"\n',
                         "struct.port_opaque: C identifier xy_port_opaque already defined by opaque_ref.port")

    def test_unknown_top_level_table(self) -> None:
        assert_objection(self, mutate(FIXTURE, "[opaque_ref.token]", "[opque_ref.token]"), "unknown table(s) [opque_ref]")

    def test_entry_attributes_begin_with_underscore(self) -> None:
        for needle, plain, where, then in (
            ('_value = 9, _docstring = "try later"', "value", "typed_const.status.err_busy", STATUS_REFS),
            ('_type = "u32", _docstring = "items seen"', "type", "struct.stats.count", STATS_REFS),
            ('_type = "stats", _ref = "out", _optional', "type", "function.open_port.pstats", []),
            ('_value = "acme"', "value", "string_const.vendor", []),
        ):
            with self.subTest(where=where):
                text = mutate(FIXTURE, needle, needle.replace(f"_{plain} = ", f"{plain} = ", 1))
                self.assertEqual(objections(text), [f"{where}: '{plain}': entry attributes begin with _", *then])

    def test_unknown_underscore_attribute_names_key_and_context(self) -> None:
        self.assertEqual(objections(mutate(FIXTURE, '_value = 3,', '_value = 3, _colour = "red",')),
                         ["untyped_bit_const.feat_b: unknown key(s) _colour", *FEAT_A_REFS])
        assert_objection(self, mutate(FIXTURE, '_ref = "in", ', '_ref = "in", _size = "len", '),
                          "function.send.buf: unknown key(s) _size")
        self.assertEqual(objections(mutate(FIXTURE, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_colour = "red"')),
                         ["opaque_ref.port: unknown key(s) _colour", *PORT_REFS])
        assert_objection(self, mutate(FIXTURE, "[_general]\n", '[_general]\n_colour = "red"\n'),
                          "_general: unknown key(s) _colour")
        assert_objection(self, mutate(FIXTURE, "[_wrapped_api]\n", '[_wrapped_api]\n_colour = "red"\n'),
                          "_wrapped_api: unknown key(s) _colour")

    def test_opaque_ref_has_only_properties(self) -> None:
        self.assertEqual(objections(mutate(FIXTURE, '_ctor = "open_port"', 'ctor = "open_port"')),
                         ["opaque_ref.port: 'ctor': an opaque_ref has no members; its properties begin with _", *PORT_REFS])

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
             'port = { _ctor = "open_port", _dtor = "destroy_port" }'),
        ):
            with self.subTest(needle=needle):
                self.assertEqual(load(mutate(FIXTURE, needle, spelled_out)), api)
        self.assertEqual(
            load(mutate(KITCHEN_SINK, '[boxed_scalar.offset]\n_docstring = "a device offset"\n_base_type = "u64"',
                        'offset = { _docstring = "a device offset", _base_type = "u64" }')),
            load(KITCHEN_SINK),
        )

    def test_ref_values(self) -> None:
        assert_objection(self, mutate(FIXTURE, '_ref = "in"', '_ref = "both"'), "function.send.buf._ref must be one of in, out, inout")
        self.assertEqual(
            [p.ref for p in load().functions[0].params], [None, "out", "out", "out"]
        )

    def test_optional_is_a_boolean(self) -> None:
        assert_objection(self, mutate(FIXTURE, "_optional = true", '_optional = "yes"'), "function.open_port.pstats._optional must be true or false")
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
                assert_objection(self, text, message)
        memory_in = load(mutate(FIXTURE, '_ref = "in", _count = "u64"', '_ref = "in", _optional = true, _count = "u64"'))
        self.assertTrue(next(f for f in memory_in.functions if f.name == "send").params[1].optional)

    def test_return_enum_needs_zero(self) -> None:
        self.assertEqual(
            objections(mutate(FIXTURE, "ok = 0", "ok = 1")),
            [f"function.{f}._return: typed_const 'status' has no zero-valued entry for success"
             for f in ("open_port", "destroy_port", "send", "spend")],
        )

    def test_quoted_library_rejected(self) -> None:
        assert_objection(self, mutate(FIXTURE, '_bound_library = "libxy.so"', '_bound_library = "lib\\"xy.so"'),
                         "_general._bound_library must not contain '\"', '\\' or a control character")
        assert_objection(self, mutate(FIXTURE, '_headers = ["driver/', '_headers = ["driver\\\\'),
                         "_wrapped_api._headers[0] must not contain '\"', '\\' or a control character")

    def test_library_and_header_refuse_control_characters(self) -> None:
        for needle, replacement, where in (
            ('_bound_library = "libxy.so"', '_bound_library = "libxy.so\\n"', "_general._bound_library"),
            ('_headers = ["driver/', '_headers = ["driver\\r/', "_wrapped_api._headers[0]"),
        ):
            with self.subTest(where=where):
                assert_objection(self, mutate(FIXTURE, needle, replacement),
                                  f"{where} must not contain '\"', '\\' or a control character")

    def test_bit_index_fits_the_base_type(self) -> None:
        for base_type, top in (("i32", 30), ("u32", 31)):
            text = mutate(FIXTURE, "[[untyped_bit_const]]\n", f'[[untyped_bit_const]]\n_base_type = "{base_type}"\n')
            for index in (top + 1, -1):
                with self.subTest(base_type=base_type, index=index):
                    self.assertEqual(
                        objections(mutate(text, "_value = 3,", f"_value = {index},")),
                        [f"untyped_bit_const.feat_b: bit index {index} is outside 0..{top} for _base_type {base_type}",
                         *FEAT_A_REFS],
                    )
            value = next(c for c in load(mutate(text, "_value = 3,", f"_value = {top},")).bit_consts if c.name == "feat_b")
            self.assertEqual(value.value, 1 << top)

    def test_version_bytes_are_0_to_255(self) -> None:
        self.assertEqual(load(mutate(FIXTURE, "[1, 2, 3, 4]", "[255, 255, 255, 255]")).version_value(), 0xFFFFFFFF)
        for version in ("[256, 2, 3, 4]", "[1, 2, 3, -1]"):
            with self.subTest(version=version):
                assert_objection(self, mutate(FIXTURE, "[1, 2, 3, 4]", version),
                                 "_general._version must be a list of 4 integers in 0..255")

    def test_docstring_terminators_rejected(self) -> None:
        for terminator in ("*/", "]]"):
            with self.subTest(terminator=terminator):
                assert_objection(self, 
                    mutate(FIXTURE, '_docstring = "wire magic"', f'_docstring = "wire {terminator} magic"'),
                    "untyped_const.magic._docstring must not contain '*/' or ']]'",
                )

    def test_docstring_line_break_rejected(self) -> None:
        for escape in ("\\n", "\\r"):
            with self.subTest(escape=escape):
                assert_objection(self, 
                    mutate(FIXTURE, '_docstring = "wire magic"', f'_docstring = "wire{escape}magic"'),
                    "untyped_const.magic._docstring must not contain a line break",
                )
        assert_objection(self, 
            mutate(FIXTURE, '_docstring = "release the port"', '_docstring = """release\nthe port"""'),
            "function.destroy_port._docstring must not contain a line break",
        )

    def test_namespace_is_an_identifier(self) -> None:
        assert_objection(self, mutate(FIXTURE, '_namespace = "xy"', '_namespace = "x-y"'),
                          "_general._namespace: 'x-y' is not an identifier")
        assert_objection(self, mutate(FIXTURE, '_namespace = "xy"', "_namespace = 5"),
                         "_general._namespace must be an identifier string")

    def test_struct_rules(self) -> None:
        for text, message in (
            (FIXTURE + '\n[struct.early]\nx = "late"\n\n[struct.late]\ny = "u32"\n',
             "struct.early.x: struct 'late' must be defined before it is used"),
            (FIXTURE + '\n[struct.empty]\n_docstring = "nothing"\n', "struct.empty: has no fields"),
        ):
            with self.subTest(message=message):
                assert_objection(self, text, message)
        self.assertEqual(objections(mutate(FIXTURE, 'bytes = "u64"', 'bytes = "memory"')),
                         ["struct.stats.bytes: 'memory' is not a field type", *STATS_REFS])

    def test_typed_const_has_entries(self) -> None:
        assert_objection(self, FIXTURE + '\n[typed_const.none]\n_docstring = "nothing"\n', "typed_const.none: has no entries")

    def test_typed_const_entries_have_distinct_values(self) -> None:
        self.assertEqual(
            objections(mutate(FIXTURE, "err_other = { _value = 0x7fffffff", "err_other = { _value = 9")),
            ["typed_const.status.err_other: value 9 already given to typed_const.status.err_busy", *STATUS_REFS],
        )

    def test_wrapped_api_rules(self) -> None:
        for needle, replacement, message in (
            ('_headers = ["driver/xy_ioctl.h"]\n', "", "_wrapped_api._headers must be a non-empty list of strings"),
            ('feat_a = "XYD_FEAT_A"', 'feat_a = "XYD-FEAT-A"', "_wrapped_api._pinned_value.feat_a: must be a macro name"),
            ("[_wrapped_api]", "[_driver_data]", "unknown table(s) [_driver_data]"),
            ('feat_a = "XYD_FEAT_A"', '[_wrapped_api.const_pins]\nfeat_a = "XYD_FEAT_A"',
             "_wrapped_api: unknown key(s) const_pins"),
            ('[_wrapped_api._pinned_value]\nfeat_a = "XYD_FEAT_A"', '_pinned_value = "x"', "_wrapped_api._pinned_value must be a table"),
            ("[_wrapped_api._pinned_value]\n", "", "_wrapped_api: unknown key(s) feat_a"),
            ('feat_a = "XYD_FEAT_A"', '_x = 1\nfeat_a = "XYD_FEAT_A"',
             "_wrapped_api._pinned_value: unknown key(s) _x"),
            ('_headers = ["driver/xy_ioctl.h"]', '_header = "driver/xy_ioctl.h"', "_wrapped_api: unknown key(s) _header"),
            ('_headers = ["driver/xy_ioctl.h"]', '_headers = "driver/xy_ioctl.h"',
             "_wrapped_api._headers must be a non-empty list of strings"),
            ('_headers = ["driver/xy_ioctl.h"]', "_headers = []", "_wrapped_api._headers must be a non-empty list of strings"),
            ('_headers = ["driver/xy_ioctl.h"]', '_headers = ["driver/xy_ioctl.h", 5]',
             "_wrapped_api._headers must be a non-empty list of strings"),
            ('_headers = ["driver/xy_ioctl.h"]', '_headers = ["driver/xy_ioctl.h", "driver/xy_ioctl.h"]',
             "_wrapped_api._headers[1]: already listed"),
        ):
            with self.subTest(message=message):
                assert_objection(self, mutate(FIXTURE, needle, replacement), message)

    def test_wrapped_api_without_pins_keeps_its_header(self) -> None:
        wrapped = load(mutate(FIXTURE, 'feat_a = "XYD_FEAT_A"\n', "")).wrapped_api
        self.assertEqual((wrapped.headers, wrapped.pins), (("driver/xy_ioctl.h",), ()))
        self.assertIsNone(load(NO_WRAPPED_API).wrapped_api)

    def test_header_is_relative_to_the_project_directory(self) -> None:
        message = "_wrapped_api._headers[0] must be relative to the project directory, not absolute or beginning with '../'"
        for header in ("/work/exercises/xy/driver/xy_ioctl.h", "../xy/driver/xy_ioctl.h"):
            with self.subTest(header=header):
                assert_objection(self, mutate(FIXTURE, '"driver/xy_ioctl.h"', f'"{header}"'), message)
        assert_objection(self, mutate(FIXTURE, '"driver/xy_ioctl.h"', '"driver/xy_ioctl.h", "../a.h"'),
                         message.replace("_headers[0]", "_headers[1]"))
        self.assertEqual(load(mutate(FIXTURE, '"driver/', '"./driver/')).wrapped_api.headers, ("./driver/xy_ioctl.h",))

    def test_typed_const_fits_its_base_type(self) -> None:
        self.assertEqual(objections(mutate(FIXTURE, "ok = 0", "ok = 0x80000000")),
                         [f"typed_const.status.ok: 2147483648 does not fit {I32}", *STATUS_REFS])
        u32 = mutate(FIXTURE, '_docstring = "call outcome"', '_base_type = "u32"')
        self.assertEqual(objections(mutate(u32, "err_busy = { _value = 9", "err_busy = { _value = -9")),
                         ["typed_const.status.err_busy: -9 does not fit u32 (0..4294967295)", *STATUS_REFS])
        # above the i32 maximum is the header's objection, not the loader's
        entries = load(mutate(u32, "0x7fffffff", "0xffffffff")).typed_consts[0].entries
        self.assertEqual(next(e for e in entries if e.name == "err_other").value, 2**32 - 1)

    def test_untyped_value_fits_its_group_base_type(self) -> None:
        for base_type, low, high in (("i32", -(2**31), 2**31 - 1), ("u32", 0, 2**32 - 1)):
            text = mutate(FIXTURE, "[[untyped_const]]\n", f'[[untyped_const]]\n_base_type = "{base_type}"\n')
            for bad in (low - 1, high + 1):
                with self.subTest(base_type=base_type, value=bad):
                    assert_objection(self, mutate(text, "max_units = 16", f"max_units = {bad}"),
                                      f"untyped_const.max_units: {bad} does not fit {base_type} ({low}..{high})")
            for good in (low, high):
                with self.subTest(base_type=base_type, value=good):
                    self.assertEqual(load(mutate(text, "max_units = 16", f"max_units = {good}")).consts[0].value, good)

    def test_sum_and_its_literal_terms_fit_the_base_type(self) -> None:
        assert_objection(self, mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbig = ["0x7fffffff", "max_units"]'),
                          f"untyped_const.big: 2147483663 does not fit {I32}")
        assert_objection(self, mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbig = ["0x80000000", "-1"]'),
                          f"untyped_const.big: term 0x80000000: 2147483648 does not fit {I32}")
        self.assertEqual(objections(mutate(FIXTURE, '["feat_a", "feat_b"]', '["feat_a", "0x80000000"]')),
                         [f"untyped_bit_const.feat_ab: term 0x80000000: 2147483648 does not fit {I32}", *FEAT_A_REFS])

    def test_sum_running_total_fits_the_base_type_term_by_term(self) -> None:
        # the final value fits; the total after the second term does not
        assert_objection(self, 
            mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbig = ["0x7fffffff", "max_units", "-16"]'),
            f"untyped_const.big: the running sum after term max_units: 2147483663 does not fit {I32}",
        )
        assert_objection(self, 
            mutate(FIXTURE, "max_units = 16", 'max_units = 16\nlow = ["-0x80000000", "-1", "1"]'),
            f"untyped_const.low: the running sum after term -1: -2147483649 does not fit {I32}",
        )
        # the same terms in an order whose every running total fits
        text = mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbig = ["0x7fffffff", "-16", "max_units"]')
        self.assertEqual(next(c for c in load(text).consts if c.name == "big").value, 2**31 - 1)

    def test_sum_terms_share_its_base_type(self) -> None:
        u32_bits = '\n[[untyped_bit_const]]\n_base_type = "u32"\nfeat_c = 0\n'
        assert_objection(self, 
            mutate(FIXTURE, "\n[[untyped_const]]", u32_bits + 'feat_x = ["feat_c", "feat_b"]\n\n[[untyped_const]]'),
            "untyped_bit_const.feat_x (u32) composes untyped_bit_const.feat_b (i32): a sum's terms share its _base_type",
        )
        u32_plain = '\n[[untyped_const]]\n_base_type = "u32"\nwire = ["max_units"]\n'
        assert_objection(self, 
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
        assert_objection(self, FIXTURE + '\n[struct.u32]\nx = "u64"\n', "struct.u32: shadows builtin type u32")

    def test_constant_uniqueness(self) -> None:
        assert_objection(self, 
            mutate(FIXTURE, "feat_a = 0\n", "feat_a = 0\napi_version = 5\n"),
            "untyped_bit_const.api_version: C identifier XY_API_VERSION already defined by the API version constant",
        )
        assert_objection(self, 
            mutate(FIXTURE, "ok = 0\n", "ok = 0\nfeat_a = 4\n"),
            "typed_const.status.feat_a: C identifier XY_FEAT_A already defined by untyped_bit_const.feat_a",
        )

    def test_string_const_rejects_control_characters(self) -> None:
        for escape in ("\\n", "\\r", "\\t", "\\u0000", "\\u001b", "\\u007f"):
            with self.subTest(escape=escape):
                assert_objection(self, 
                    mutate(FIXTURE, 'product = "xy widget"', f'product = "xy{escape}widget"'),
                    "string_const.product: value must not contain '\"', '\\' or a control character",
                )

    def test_ctor_cannot_cache_a_memory_out(self) -> None:
        assert_objection(self, 
            mutate(FIXTURE,
                'generation = { _type = "u32", _ref = "out" }',
                'generation = { _type = "u32", _ref = "out" }\nblob = { _type = "memory", _ref = "out", _count = "u32" }',
            ),
            "opaque_ref.port._ctor: function.open_port.blob: a constructor cannot cache a memory out parameter",
        )

    def test_ctor_has_no_inout_parameter(self) -> None:
        assert_objection(self, 
            mutate(FIXTURE, 'generation = { _type = "u32", _ref = "out" }', 'generation = { _type = "u32", _ref = "inout" }'),
            "opaque_ref.port._ctor: function.open_port.generation: a constructor has no inout parameter",
        )

    def test_underscore_keys_are_properties_not_members(self) -> None:
        self.assertEqual(objections(mutate(FIXTURE, "bytes = ", "_bytes = ")), ["struct.stats: unknown key(s) _bytes", *STATS_REFS])
        assert_objection(self, mutate(FIXTURE, "max_units = ", "_max_units = "), "untyped_const[0]: unknown key(s) _max_units")
        assert_objection(self, mutate(FIXTURE, "unit = ", "_unit = "), "function.open_port: unknown key(s) _unit")
        self.assertEqual(objections(mutate(FIXTURE, "ok = 0", "_ok = 0")), ["typed_const.status: unknown key(s) _ok", *STATUS_REFS])
        assert_objection(self, mutate(FIXTURE, 'product = "xy', '_product = "xy'), "string_const[0]: unknown key(s) _product")
        assert_objection(self, mutate(FIXTURE, '_return = "status"\nunit', "unit"),
                         "function.open_port: missing '_return' naming a typed_const")

    def test_docstring_is_a_member_name(self) -> None:
        load(mutate(FIXTURE, "bytes = ", "docstring = "))

    def test_undecodable_definition_is_a_definition_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "xy_api.adef.toml"
            path.write_bytes(b'[_general]\n_namespace = "\xff"\n')  # deliberately not UTF-8
            with self.assertRaises(model.DefinitionError):
                model.load(path)

    def test_single_table_constants_are_rejected(self) -> None:
        for key in ("untyped_const", "untyped_bit_const", "string_const"):
            with self.subTest(key=key):
                assert_objection(self, mutate(NO_WRAPPED_API, f"[[{key}]]", f"[{key}]"), f"[{key}] must be an array of tables, [[{key}]]")

    def test_string_group_has_no_base_type(self) -> None:
        assert_objection(self, 
            mutate(FIXTURE, "[[string_const]]", '[[string_const]]\n_base_type = "u32"'),
            "string_const[0]: unknown key(s) _base_type",
        )

    def test_empty_group_is_rejected(self) -> None:
        text = mutate(FIXTURE, "[[untyped_const]]\n", '[[untyped_const]]\n_docstring = "none"\n\n[[untyped_const]]\n')
        assert_objection(self, text, "untyped_const[0]: has no entries")

    def test_base_type(self) -> None:
        assert_objection(self, 
            mutate(FIXTURE, "[[untyped_const]]\n", '[[untyped_const]]\n_base_type = "u64"\n'),
            "untyped_const[0]._base_type must be one of i32, u32",
        )
        self.assertEqual(
            objections(mutate(FIXTURE, '_docstring = "call outcome"', '_base_type = "int"')),
            ["typed_const.status._base_type must be one of i32, u32", *STATUS_REFS],
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
        assert_objection(self, mutate(FIXTURE, 'unit = "u32"', 'unit = "u128"'), "function.open_port.unit: unknown type 'u128'")

    def test_unknown_return_type(self) -> None:
        assert_objection(self, mutate(FIXTURE, '_docstring = "release the port"\n_return = "status"',
                                          '_return = "nope"'), "function.destroy_port._return: unknown typed_const 'nope'")

    def test_duplicate_type_name_across_categories(self) -> None:
        assert_objection(self, FIXTURE + "\n[opaque_ref.stats]\n", "struct.stats: type name already defined in opaque_ref")

    def test_pin_names_undefined_constant(self) -> None:
        assert_objection(self, FIXTURE + 'feat_z = "XY_FEAT_Z"\n', "_wrapped_api._pinned_value.feat_z: pins undefined untyped_bit_const 'feat_z'")

    def test_composed_constant_must_be_earlier(self) -> None:
        text = mutate(NO_WRAPPED_API, '["feat_a", "feat_b"]', '["feat_a", "feat_c"]')
        assert_objection(
            self, text,
            "untyped_bit_const.feat_ab: composes unknown constant 'feat_c' (only earlier untyped_bit_const entries or literals)",
        )

    def test_bit_sum_refuses_overlapping_terms(self) -> None:
        assert_objection(self, 
            mutate(NO_WRAPPED_API, '["feat_a", "feat_b"]', '["feat_a", "1"]'),
            "untyped_bit_const.feat_ab: feat_a and 1 share bits",
        )

    def test_composed_term_must_be_a_literal_or_known_entry(self) -> None:
        assert_objection(self, 
            mutate(NO_WRAPPED_API, '["feat_a", "feat_b"]', '["feat_a", "bogus"]'),
            "untyped_bit_const.feat_ab: composes unknown constant 'bogus' (only earlier untyped_bit_const entries or literals)",
        )
        assert_objection(self, 
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
                assert_objection(self, 
                    mutate(FIXTURE, "max_units = 16", f'max_units = 16\ntotal = ["max_units", "{term}"]'),
                    f"untyped_const.total: term '{term}' is neither an entry name nor a literal (decimal or 0x-prefixed, "
                    "an optional leading '-')",
                )

    def test_composed_entry_dict_form_equals_naked_list(self) -> None:
        api = load(KITCHEN_SINK)
        naked = mutate(KITCHEN_SINK, 'feat_lit = { _value = ["feat_a", "4"] }', 'feat_lit = ["feat_a", "4"]')
        self.assertEqual(load(naked), api)

    def test_memory_needs_a_ref(self) -> None:
        assert_objection(self, mutate(FIXTURE, '_ref = "in", ', ""), "function.send.buf: a 'memory' parameter needs _ref")

    def test_memory_count(self) -> None:
        assert_objection(self, mutate(FIXTURE, '_count = "u64", ', ""),
                          "function.send.buf: a 'memory' parameter requires _count, one of u8, u16, u32, u64")
        for count in ("port", "i64", "f64"):
            with self.subTest(count=count):
                assert_objection(self, mutate(FIXTURE, '_count = "u64"', f'_count = "{count}"'),
                                 "function.send.buf: a 'memory' parameter requires _count, one of u8, u16, u32, u64")
        assert_objection(self, mutate(FIXTURE, 'unit = "u32"', 'unit = { _type = "u32", _count = "u32" }'),
                          "function.open_port.unit._count: only a 'memory' parameter has a count")
        assert_objection(self, mutate(FIXTURE, 'hport = "port"\nbuf', 'buf_count = "u32"\nbuf'),
                          "function.send.buf: its count parameter buf_count is already a parameter")
        self.assertEqual(load().functions[2].params[1].count_type, "u64")

    def test_missing_general(self) -> None:
        assert_objection(self, "[function]\n", "missing [_general] table")

    def test_unknown_format(self) -> None:
        self.assertEqual(objections(mutate(FIXTURE, '_format = "hex" }\n\n[[opaque', '_format = "oct" }\n\n[[opaque')),
                         ["typed_const.status.err_other._format must be one of dec, hex", *STATUS_REFS])

    def test_ctor_needs_one_out_of_the_opaque(self) -> None:
        assert_objection(self, mutate(FIXTURE, '_ctor = "open_port"', '_ctor = "send"'), 
                         "opaque_ref.port._ctor: 'send' must name a function with exactly one port parameter of _ref \"out\"")

    def test_ctor_and_dtor_are_function_names(self) -> None:
        for key in ("_ctor", "_dtor"):
            with self.subTest(key=key):
                self.assertEqual(objections(mutate(FIXTURE, f'{key} = "', f'{key} = 5 # "')),
                                 [f"opaque_ref.port.{key} must be a function name", *PORT_REFS])

    def test_dtor_takes_only_the_opaque(self) -> None:
        for dtor in ("send", "nope"):
            with self.subTest(dtor=dtor):
                assert_objection(self, mutate(FIXTURE, '_dtor = "destroy_port"', f'_dtor = "{dtor}"'),
                                  f"opaque_ref.port._dtor: '{dtor}' must name a function whose only parameter is a port by value")

    def test_dtor_requires_ctor(self) -> None:
        assert_objection(self, mutate(FIXTURE, '_ctor = "open_port"\n', ""), "opaque_ref.port._dtor: requires _ctor")

    def test_string_const_rejects_a_quote(self) -> None:
        assert_objection(self, mutate(FIXTURE, 'product = "xy widget"', "product = 'xy \"widget\"'"),
                         "string_const.product: value must not contain '\"', '\\' or a control character")

    def test_plain_and_string_constants_share_the_constant_namespace(self) -> None:
        assert_objection(self, mutate(FIXTURE, "max_units = 16", "ok = 16"),
                         "typed_const.status.ok: C identifier XY_OK already defined by untyped_const.ok")
        assert_objection(self, mutate(FIXTURE, 'product = "xy widget"', 'max_units = "x"'),
                         "string_const.max_units: C identifier XY_MAX_UNITS already defined by untyped_const.max_units")

    def test_to_string_is_a_name(self) -> None:
        for needle, value, message, then in (
            ('_to_string = "to_string"', '"_x"',
             "typed_const.status._to_string: '_x': a key beginning with '_' is a property, not a name", STATUS_REFS),
            ('_to_string = "to_string"', "5", "typed_const.status._to_string must be an identifier", STATUS_REFS),
            ('_to_string = "feat_to_string"', '"9x"', "untyped_bit_const[0]._to_string: '9x' is not an identifier", FEAT_A_REFS),
            ('_to_string = "limit_to_string"', '"a-b"', "untyped_const[0]._to_string: 'a-b' is not an identifier", []),
        ):
            with self.subTest(message=message):
                self.assertEqual(objections(mutate(FIXTURE, needle, f"_to_string = {value}")), [message, *then])

    def test_string_group_has_no_to_string(self) -> None:
        assert_objection(self, 
            mutate(FIXTURE, "[[string_const]]\n", '[[string_const]]\n_to_string = "product_to_string"\n'),
            "string_const[0]: unknown key(s) _to_string",
        )

    def test_class_must_be_an_identifier(self) -> None:
        assert_objection(self, FIXTURE + '\n[opaque_ref.spare]\n_class = "a-b"\n', "opaque_ref.spare._class: 'a-b' is not an identifier")
        assert_objection(self, FIXTURE + '\n[opaque_ref.spare]\n_class = 5\n', "opaque_ref.spare._class must be an identifier")

    def test_class_is_lowercase(self) -> None:
        assert_objection(self, FIXTURE + '\n[opaque_ref.spare]\n_class = "DataLink"\n',
                         "opaque_ref.spare._class: 'DataLink' must be lowercase; each binding applies its own casing")
        self.assertEqual(load(mutate(FIXTURE, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_class = "link_2"'))
                         .opaque_refs[0].class_name, "link_2")


class CollectedErrors(unittest.TestCase):
    def test_independent_errors_in_different_items_all_report_in_document_order(self) -> None:
        self.assertEqual(objections(TWO_BAD_RETURNS), [
            "function.destroy_port._return: unknown typed_const 'nope'",
            "function.spend._return: unknown typed_const 'gone'",
        ])

    def test_errors_in_one_function_all_report_in_document_order(self) -> None:
        text = mutate(mutate(FIXTURE, 'unit = "u32"', 'unit = "u128"'),
                      'generation = { _type = "u32", _ref = "out" }', 'generation = { _type = "u32", _ref = "both" }')
        self.assertEqual(objections(text), [
            "function.open_port.unit: unknown type 'u128'",
            "function.open_port.generation._ref must be one of in, out, inout",
        ])

    def test_order_is_the_documents_not_the_loaders(self) -> None:
        # the loader reads typed_const before struct; the document writes struct first
        text = MINIMAL + '\n[[struct]]\n[struct.s]\nx = "nope"\n\n[[typed_const]]\n[typed_const.e]\nok = "zero"\n'
        self.assertEqual(objections(text), [
            "struct.s.x: unknown type 'nope'",
            "typed_const.e.ok: value must be an integer",
        ])

    def test_a_failure_leaving_nothing_to_parse_stops_alone(self) -> None:
        for text, message in (
            (mutate(TWO_BAD_RETURNS, "[opaque_ref.token]", "[opque_ref.token]"), "unknown table(s) [opque_ref]"),
            (mutate(TWO_BAD_RETURNS, '_namespace = "xy"', '_namespace = "x-y"'), "_general._namespace: 'x-y' is not an identifier"),
        ):
            with self.subTest(message=message):
                self.assertEqual(objections(text), [message])


BOXED = FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.offset]\n_base_type = "u64"\n'


class BoxedScalar(unittest.TestCase):
    def test_usable_with_any_ref_optional_as_a_scalar_and_as_a_struct_field(self) -> None:
        text = BOXED + (
            '\n[struct.span]\nat = "offset"\n'
            '\n[function.move]\n_return = "status"\nsrc = { _type = "offset", _ref = "in", _optional = true }\n'
            'dst = { _type = "offset", _ref = "inout" }\n'
        )
        api = load(text)
        self.assertEqual(next(s for s in api.structs if s.name == "span").fields[0].type, "offset")
        move = next(f for f in api.functions if f.name == "move")
        self.assertEqual([(p.ref, p.optional) for p in move.params], [("in", True), ("inout", False)])

    def test_base_type_is_any_integer_builtin_and_required(self) -> None:
        for base_type in ("i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"):
            with self.subTest(base_type=base_type):
                api = load(mutate(BOXED, '_base_type = "u64"', f'_base_type = "{base_type}"'))
                self.assertEqual(api.boxed_scalars[0].base_type, base_type)
        message = "boxed_scalar.offset._base_type is required, one of i8, u8, i16, u16, i32, u32, i64, u64"
        for value in ('"f64"', '"memory"', '"status"', "8", '["u64"]'):
            with self.subTest(value=value):
                assert_objection(self, mutate(BOXED, '_base_type = "u64"', f"_base_type = {value}"), message)
        assert_objection(self, mutate(BOXED, '_base_type = "u64"', '_docstring = "no base"'), message)

    def test_has_only_properties(self) -> None:
        assert_objection(self, mutate(BOXED, '_base_type = "u64"', '_base_type = "u64"\nvalue = "u64"'),
                          "boxed_scalar.offset: 'value': a boxed_scalar has no members; its properties begin with _")
        assert_objection(self, mutate(BOXED, '_base_type = "u64"', '_base_type = "u64"\n_class = "x"'),
                          "boxed_scalar.offset: unknown key(s) _class")

    def test_refused_as_return_and_with_count(self) -> None:
        assert_objection(self, BOXED + '\n[function.where]\n_return = "offset"\n', "function.where._return: unknown typed_const 'offset'")
        assert_objection(self, BOXED + '\n[function.where]\n_return = "status"\nat = { _type = "offset", _ref = "in", _count = "u32" }\n',
                          "function.where.at._count: only a 'memory' parameter has a count")

    def test_shares_the_type_namespace_and_the_c_identifiers(self) -> None:
        assert_objection(self, BOXED + '\n[struct.offset]\nx = "u32"\n', "struct.offset: type name already defined in boxed_scalar")
        assert_objection(self, mutate(BOXED, "[boxed_scalar.offset]", "[boxed_scalar.port]"),
                          "boxed_scalar.port: type name already defined in opaque_ref")
        assert_objection(self, mutate(BOXED, "[boxed_scalar.offset]", "[boxed_scalar.u64]"), "boxed_scalar.u64: shadows builtin type u64")
        assert_objection(self, BOXED + '\n[function.offset]\n_return = "status"\n',
                          "function.offset: C identifier xy_offset already defined by boxed_scalar.offset")


class Groups(unittest.TestCase):
    def test_a_named_kind_written_without_groups_is_refused(self) -> None:
        for kind in ("typed_const", "opaque_ref", "boxed_scalar", "struct", "function"):
            with self.subTest(kind=kind):
                assert_objection(self, MINIMAL + f"\n[{kind}.x]\n", f"[{kind}] must be an array of tables, [[{kind}]]")

    def test_a_group_without_members_is_refused_by_its_index(self) -> None:
        assert_objection(self, FIXTURE + '\n[[function]]\n_docstring = "none"\n', "function[1]: has no entries")

    def test_a_named_kinds_group_has_only_a_docstring(self) -> None:
        assert_objection(self, mutate(FIXTURE, "[[struct]]\n", '[[struct]]\n_colour = "red"\n'), "struct[0]: unknown key(s) _colour")

    def test_a_group_docstring_has_no_line_break(self) -> None:
        assert_objection(self, FIXTURE + '\n[[function]]\n_docstring = "a\\nb"\n[function.reset]\n_return = "status"\n',
                         "function[1]._docstring must not contain a line break")

    def test_an_item_name_is_unique_across_its_kinds_groups(self) -> None:
        assert_objection(self, FIXTURE + '\n[[function]]\n[function.spend]\n_return = "status"\n',
                         "function.spend: already defined in function[0]")

    def test_an_item_body_is_a_table(self) -> None:
        assert_objection(self, mutate(FIXTURE, "[[function]]\n", "[[function]]\nreset = 5\n"), "function.reset must be a table")


class Shape(unittest.TestCase):
    def test_success_entry_is_the_zero_valued_one(self) -> None:
        text = mutate(FIXTURE, "ok = 0\nerr_busy = { _value = 9", "err_busy = { _value = 9")
        api = load(mutate(text, 'err_other = { _value = 0x7fffffff, _format = "hex" }',
                          'err_other = { _value = 0x7fffffff, _format = "hex" }\nfine = 0'))
        self.assertEqual(api.success_entry(api.functions[0]).name, "fine")


if __name__ == "__main__":
    unittest.main()
