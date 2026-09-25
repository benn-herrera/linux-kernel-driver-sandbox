import re
import unittest

from api_gen import emit_cpp_wrapper, model, naming
from api_gen.tests.support import C_BASE_TYPES, FIXTURE, KITCHEN_SINK, load, mutate


def wrapper(text: str = FIXTURE) -> str:
    return emit_cpp_wrapper.wrapper(load(text), source_name="xy_api.adef.toml", stem="xy_api")


class Wrapper(unittest.TestCase):
    def setUp(self) -> None:
        self.text = wrapper()

    def test_includes_the_c_header_then_only_standard_headers(self) -> None:
        includes = [line for line in self.text.splitlines() if line.startswith("#include")]
        self.assertEqual(includes[0], '#include "xy_api.h"')
        for include in includes[1:]:
            self.assertRegex(include, r"#include <\w+>")
        self.assertTrue(self.text.rstrip().endswith("}  // namespace xy"))

    def test_no_exceptions_no_allocation(self) -> None:
        for absent in ("throw", "new ", "malloc", "iostream"):
            self.assertNotIn(absent, self.text)

    def test_class_only_for_opaque_with_ctor(self) -> None:
        self.assertIn("class Port {\n", self.text)
        self.assertNotIn("class Token", self.text)
        self.assertNotIn("xy_spend", self.text)

    def test_no_dtor_no_release(self) -> None:
        text = wrapper(mutate(FIXTURE, '_dtor = "destroy_port"\n', ""))
        self.assertNotIn("~Port", text)
        self.assertNotIn("release()", text)
        self.assertIn("  Status destroy_port() {\n", text)

    def test_references_by_ref(self) -> None:
        text = wrapper(KITCHEN_SINK)
        self.assertIn("  Status configure(const Stats& cfg, const uint32_t& limit, Mode mode, xy_token who) {\n", text)
        self.assertIn("  Status stats_of(Stats& out, uint32_t& pcount, xy_link& plink) {\n", text)
        self.assertIn("  Status bump(uint32_t& level, Stats& tally, void* data, uint32_t data_count) {\n", text)
        self.assertIn("  Status send(const void* buf, uint64_t buf_count) {\n", text)
        self.assertIn("    return Status(xy_send(handle_, buf, buf_count));\n", text)


class BaseTypes(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = wrapper(KITCHEN_SINK)

    def test_group_constants_take_the_group_base_type_under_its_docstring(self) -> None:
        types = {name: c_type for c_type, name in re.findall(r"^inline constexpr (\w+) (\w+) = ", self.text, re.M)}
        self.assertEqual(types.pop("API_VERSION"), "uint32_t")
        expected = {}
        lines = self.text.splitlines()
        for group in (*self.api.bit_const_groups, *self.api.const_groups):
            base = C_BASE_TYPES[group.base_type]
            expected |= {c.key.upper(): base for c in group.entries}
            key = group.entries[0].key.upper()
            first = lines.index(f"inline constexpr {base} {key} = XY_{key};")
            self.assertEqual(lines[first - 1], f"// {group.docstring}" if group.docstring else "")
        self.assertEqual(types, expected)

    def test_enum_class_underlying_type_is_the_base_type(self) -> None:
        for t in self.api.typed_consts:
            self.assertIn(
                f"enum class [[nodiscard]] {naming.upper_camel(t.name)} : {C_BASE_TYPES[t.base_type]} {{\n", self.text
            )


class Refusals(unittest.TestCase):
    def test_member_collision_is_an_error(self) -> None:
        with self.assertRaises(model.DefinitionError) as caught:
            wrapper(mutate(FIXTURE, "[function.send]", "[function.release]"))
        self.assertIn("C++ wrapper: class Port: release would be defined more than once", str(caught.exception))

    def test_namespace_collision_is_an_error(self) -> None:
        with self.assertRaises(model.DefinitionError) as caught:
            wrapper(mutate(FIXTURE, "[[untyped_const]]\n", "[[untyped_const]]\nx = 1\n") + '\n[struct.x]\nv = "u32"\n')
        self.assertIn("C++ wrapper: namespace xy: X would be defined more than once", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
