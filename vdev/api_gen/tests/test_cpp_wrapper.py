import re
import unittest

from api_gen import emit_cpp_wrapper, naming
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


class OptionalParam(unittest.TestCase):
    def setUp(self) -> None:
        self.text = wrapper(KITCHEN_SINK)

    def test_pointer_with_default_instead_of_reference(self) -> None:
        self.assertIn("  Status annotate(const Stats* note = nullptr) {\n", self.text)
        self.assertIn("    return Status(xy_annotate(handle_, note));\n", self.text)

    def test_ctor_cached_outref_unaffected(self) -> None:
        self.assertIn("static Port create(uint32_t unit, Status* result = nullptr) {\n", self.text)

    def test_default_omitted_when_a_non_optional_parameter_follows(self) -> None:
        text = wrapper(mutate(
            KITCHEN_SINK,
            'limit = { _type = "u32", _ref = "in" }',
            'limit = { _type = "u32", _ref = "in", _optional = true }',
        ))
        self.assertIn(
            "  Status configure(const Stats& cfg, const uint32_t* limit, Mode mode, xy_token who) {\n", text
        )


class BaseTypes(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = wrapper(KITCHEN_SINK)

    def test_untyped_constants_are_auto_from_the_header_macro_under_their_docstring(self) -> None:
        types = {name: c_type for c_type, name in re.findall(r"^inline constexpr (.+) (\w+) = ", self.text, re.M)}
        expected = {"API_VERSION": "auto"}
        lines = self.text.splitlines()
        for group in (*self.api.bit_const_groups, *self.api.const_groups):
            expected |= {c.name.upper(): "auto" for c in group.entries}
            key = group.entries[0].name.upper()
            first = lines.index(f"inline constexpr auto {key} = XY_{key};")
            self.assertEqual(lines[first - 1], f"// {group.docstring}" if group.docstring else "")
        expected |= {c.name.upper(): "const char*" for c in self.api.string_consts}
        self.assertEqual(types, expected)

    def test_enum_class_underlying_type_is_the_base_type(self) -> None:
        for t in self.api.typed_consts:
            self.assertIn(
                f"enum class [[nodiscard]] {naming.upper_camel(t.name)} : {C_BASE_TYPES[t.base_type]} {{\n", self.text
            )


class Validate(unittest.TestCase):
    def validate(self, text: str) -> list[str]:
        return emit_cpp_wrapper.validate(load(text))

    def test_kitchen_sink_has_no_objection(self) -> None:
        self.assertEqual(self.validate(KITCHEN_SINK), [])

    def test_cpp_keyword_as_name(self) -> None:
        for text, message in (
            (mutate(FIXTURE, "unit = ", "class = "), "wrapper: function.open_port.class: 'class' is a C++ keyword"),
            (mutate(FIXTURE, "count = { _type", "template = { _type"), "wrapper: struct.stats.template: 'template' is a C++ keyword"),
            (FIXTURE + '\n[function.new]\n_return = "status"\n', "wrapper: function.new: 'new' is a C++ keyword"),
        ):
            with self.subTest(message=message):
                self.assertIn(message, self.validate(text))

    def test_name_that_is_also_a_c_keyword_is_worded_as_one(self) -> None:
        # C already forbids it (the header refuses it too), so the wrapper's message
        # matches the header's word for word: `__main__` collapses both into one line.
        self.assertIn(
            "wrapper: struct.stats.int: 'int' is a C keyword",
            self.validate(mutate(FIXTURE, "bytes = ", "int = ")),
        )

    def test_lua_keyword_is_not_its_objection(self) -> None:
        self.assertEqual(self.validate(mutate(FIXTURE, "bytes = ", "end = ")), [])

    def test_generated_names_are_refused_as_parameters(self) -> None:
        for needle, name, where in (
            ('unit = "u32"', "result", "function.open_port.result"),
            ('unit = "u32"', "status", "function.open_port.status"),
            ('buf = { _type', "handle", "function.send.handle"),
            ('buf = { _type', "handle_", "function.send.handle_"),
        ):
            with self.subTest(name=name):
                replacement = needle.replace(needle.split(" ")[0], name, 1)
                self.assertEqual(
                    self.validate(mutate(FIXTURE, needle, replacement)),
                    [f"wrapper: {where}: '{name}' is a name the generated code uses"],
                )

    def test_every_generated_name_is_used_by_the_generated_code(self) -> None:
        text = wrapper(KITCHEN_SINK)
        for name in emit_cpp_wrapper.GENERATED_NAMES:
            with self.subTest(name=name):
                self.assertRegex(text, rf"(?<![\w.]){name}(?!\w)")

    def test_member_collision(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "[function.send]", "[function.release]")),
            ["wrapper: class Port: release would be defined more than once, by the wrapper's own member and function.release"],
        )

    def test_namespace_collision(self) -> None:
        text = mutate(FIXTURE, "[[untyped_const]]\n", "[[untyped_const]]\nx = 1\n") + '\n[struct.x]\nv = "u32"\n'
        self.assertEqual(
            self.validate(text), ["wrapper: namespace xy: X would be defined more than once, by untyped_const.x and struct.x"]
        )

    def test_enums_may_share_a_conversion_name(self) -> None:
        api = load(KITCHEN_SINK)
        self.assertEqual({t.to_string for t in api.typed_consts}, {"to_string"})
        self.assertEqual(emit_cpp_wrapper.validate(api), [])

    def test_conversion_collisions(self) -> None:
        for needle, name, message in (
            ('_to_string = "limit_to_string"', "to_string",
             "to_string would be defined more than once, by untyped_const[0]._to_string and typed_const.status._to_string"),
            ('_to_string = "feat_to_string"', "limit_to_string",
             "limit_to_string would be defined more than once, by untyped_bit_const[0]._to_string and untyped_const[0]._to_string"),
            ('_to_string = "limit_to_string"', "Stats",
             "Stats would be defined more than once, by struct.stats and untyped_const[0]._to_string"),
        ):
            with self.subTest(message=message):
                text = mutate(FIXTURE, needle, f'_to_string = "{name}"')
                self.assertEqual(self.validate(text), [f"wrapper: namespace xy: {message}"])


CONVERSION = re.compile(r"^inline (const char\*|std::string) (\w+)\((\w+) value\) \{$", re.M)


class ToString(unittest.TestCase):
    def test_signatures_in_fixture(self) -> None:
        self.assertEqual(
            CONVERSION.findall(wrapper()),
            [
                ("std::string", "feat_to_string", "int32_t"),
                ("std::string", "limit_to_string", "int32_t"),
                ("const char*", "to_string", "Status"),
            ],
        )

    def test_only_groups_with_the_property_have_a_conversion(self) -> None:
        self.assertEqual(
            [name for _, name, param in CONVERSION.findall(wrapper(KITCHEN_SINK))],
            ["access_to_string", "limit_to_string", "to_string", "to_string"],
        )
        text = FIXTURE
        for needle in ('_to_string = "feat_to_string"\n', '_to_string = "limit_to_string"\n', '_to_string = "to_string"\n'):
            text = mutate(text, needle, "")
        text = wrapper(text)
        self.assertEqual(CONVERSION.findall(text), [])
        self.assertNotIn("#include <string>", text)
        self.assertNotIn("#include <charconv>", text)

    def test_parameter_is_the_group_base_type(self) -> None:
        text = wrapper(mutate(KITCHEN_SINK, '_base_type = "u32"\nmagic', '_base_type = "u32"\n_to_string = "wire_to_string"\nmagic'))
        self.assertIn(("std::string", "wire_to_string", "uint32_t"), CONVERSION.findall(text))

    def test_switch_names_the_last_entry_of_a_shared_value(self) -> None:
        text = wrapper(KITCHEN_SINK)
        self.assertIn('    case Status::ErrAgain: return "ERR_AGAIN";\n', text)
        self.assertNotIn("case Status::ErrBusy:", text)
        self.assertIn('return "UNKNOWN_STATUS";', text)
        self.assertIn('    case MAX_UNITS: return "MAX_UNITS";\n', text)
        self.assertIn('return "UNKNOWN";', text)

    def test_bit_conversion_tests_only_single_bit_entries(self) -> None:
        text = wrapper(KITCHEN_SINK)
        self.assertIn("  if (value & ACC_A) {\n", text)
        self.assertIn("  if (value & ACC_B) {\n", text)
        self.assertNotIn("value & ACC_AB", text)

if __name__ == "__main__":
    unittest.main()
