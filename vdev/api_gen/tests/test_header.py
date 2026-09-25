import unittest

from api_gen import emit_c, model
from api_gen.tests.support import FIXTURE, KITCHEN_SINK, load, mutate, param_lists


class Preprocessor(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_c.header(self.api, source_name="xy_api.adef.toml")

    def test_only_permitted_preprocessor_lines(self) -> None:
        allowed = ("#pragma once", "#include", "#if", "#else", "#endif", "# define", "# include")
        for line in self.text.splitlines():
            if line.startswith("#"):
                self.assertTrue(line.startswith(allowed), line)

    def test_consumer_includes_only_stdint(self) -> None:
        prelude = self.text[: self.text.rindex("#if defined(XY_IMPL)")]
        include_lines = [line for line in prelude.splitlines() if line.startswith(("#include", "# include"))]
        self.assertEqual(include_lines, ["#include <stdint.h>"])


class Pins(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_c.header(self.api, source_name="xy_api.adef.toml")

    def test_abi_pins_present_with_driver_data(self) -> None:
        block = self.text[self.text.rindex("XY_API xy_status ") :]
        self.assertEqual(block.count("#if defined(XY_IMPL)"), 1)
        block = block[block.index("#if defined(XY_IMPL)") :]
        self.assertIn("# include <assert.h>", block)
        self.assertIn('# include "xy/driver/xy_ioctl.h"', block)
        self.assertRegex(block, r"static_assert\(XY_FEAT_A == XYD_FEAT_A, \"[^\"]+\"\);")

    def test_abi_pins_absent_without_driver_data(self) -> None:
        text = emit_c.header(load(FIXTURE[: FIXTURE.index("[_driver_data]")]), source_name="xy_api.adef.toml")
        self.assertNotIn("ABI pins", text)
        self.assertNotIn("static_assert", text)


class Declarations(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = emit_c.header(self.api, source_name="xy_api.adef.toml")

    def test_type_mapping_follows_the_spec_table(self) -> None:
        rows = (
            (("i8", None), "int8_t"),
            (("u8", None), "uint8_t"),
            (("i16", None), "int16_t"),
            (("u16", None), "uint16_t"),
            (("i32", None), "int32_t"),
            (("u32", None), "uint32_t"),
            (("i64", None), "int64_t"),
            (("u64", None), "uint64_t"),
            (("f32", None), "float"),
            (("f64", None), "double"),
            (("f64", "in"), "const double*"),
            (("i64", "out"), "int64_t*"),
            (("status", None), "xy_status"),
            (("stats", None), "xy_stats"),
            (("port", None), "xy_port"),
            (("stats", "in"), "const xy_stats*"),
            (("stats", "out"), "xy_stats*"),
            (("stats", "inout"), "xy_stats*"),
            (("u32", "in"), "const uint32_t*"),
            (("u32", "out"), "uint32_t*"),
            (("u32", "inout"), "uint32_t*"),
            (("memory", "in"), "const void*"),
            (("memory", "out"), "void*"),
            (("memory", "inout"), "void*"),
        )
        for (type_name, ref), expected in rows:
            count_type = "u32" if type_name == "memory" else None
            param = model.Param(name="p", type=type_name, ref=ref, count_type=count_type, optional=False, docstring=None)
            with self.subTest(type=type_name, ref=ref):
                self.assertEqual(emit_c.param_type(self.api, param), expected)

    def test_functions_declared_in_document_order_with_parameters_in_order(self) -> None:
        decls = param_lists(self.text, r"XY_API xy_status ")
        self.assertEqual(list(decls), [f.name for f in self.api.functions])
        for f in self.api.functions:
            with self.subTest(function=f.name):
                if f.params:
                    names = [s.rsplit(" ", 1)[1] for s in decls[f.name].split(", ")]
                    expected = [n for p in f.params for n in ([p.name, f"{p.name}_count"] if p.type == "memory" else [p.name])]
                    self.assertEqual(names, expected)
                else:
                    self.assertEqual(decls[f.name], "void")

    def test_memory_is_a_pointer_and_count_pair(self) -> None:
        decls = param_lists(self.text, r"XY_API xy_status ")
        self.assertEqual(decls["send"], "xy_port hport, const void* buf, uint64_t buf_count")
        self.assertEqual(decls["recv"], "xy_port hport, void* pdst, uint32_t pdst_count")
        self.assertEqual(
            decls["bump"], "xy_port hport, uint32_t* level, xy_stats* tally, void* data, uint32_t data_count"
        )

    def test_bit_constants_use_the_spec_spelling(self) -> None:
        self.assertRegex(self.text, r"XY_FEAT_B = \(1u << 3\)")
        self.assertIn("XY_FEAT_AB = XY_FEAT_A | XY_FEAT_B", self.text)
        self.assertIn("XY_FEAT_ALL = XY_FEAT_AB", self.text)

    def test_each_constant_group_is_one_enum_under_its_docstring(self) -> None:
        lines = self.text.splitlines()
        for group in (*self.api.bit_const_groups, *self.api.const_groups):
            first = next(i for i, line in enumerate(lines) if line.startswith(f"  XY_{group.entries[0].name.upper()} = "))
            with self.subTest(first=group.entries[0].name):
                self.assertEqual(lines[first - 1], "enum {")
                self.assertEqual(lines[first - 2], f"/* {group.docstring} */" if group.docstring else "")
                self.assertEqual(lines[first + len(group.entries)], "};")

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


class Validate(unittest.TestCase):
    def test_kitchen_sink_has_no_objection(self) -> None:
        self.assertEqual(emit_c.validate(load(KITCHEN_SINK)), [])

    def test_c_keyword_as_name(self) -> None:
        for text, message in (
            (mutate(FIXTURE, "bytes = ", "int = "), "header: struct.stats.int: 'int' is a C keyword"),
            (mutate(FIXTURE, 'unit = "u32"', 'restrict = "u32"'),
             "header: function.open_port.restrict: 'restrict' is a C keyword"),
            (FIXTURE + '\n[function.while]\n_return = "status"\n', "header: function.while: 'while' is a C keyword"),
        ):
            with self.subTest(message=message):
                self.assertIn(message, emit_c.validate(load(text)))

    def test_other_languages_keywords_are_not_its_objection(self) -> None:
        self.assertEqual(emit_c.validate(load(mutate(FIXTURE, "bytes = ", "end = "))), [])
        self.assertEqual(emit_c.validate(load(mutate(FIXTURE, "bytes = ", "class = "))), [])


if __name__ == "__main__":
    unittest.main()
