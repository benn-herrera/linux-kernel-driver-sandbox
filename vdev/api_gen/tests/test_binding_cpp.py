import re
import unittest

from api_gen.emitters import emit_binding_cpp
from api_gen.tests.support import FIXTURE, KITCHEN_SINK, load, mutate


def wrapper(text: str = FIXTURE) -> str:
    return emit_binding_cpp.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", library=None, project="xy")


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


class BoxedScalar(unittest.TestCase):
    def setUp(self) -> None:
        self.text = wrapper(KITCHEN_SINK)

    def test_methods_take_it_as_the_c_signature_does(self) -> None:
        self.assertIn("  Status echo_offset(Offset pos, Offset& ppos) {\n", self.text)
        self.assertIn("    return Status(xy_echo_offset(handle_, pos, &ppos));\n", self.text)
        text = wrapper(KITCHEN_SINK + (
            '\n[function.move]\n_return = "status"\nhport = "port"\n'
            'src = { _type = "offset", _ref = "in" }\ndst = { _type = "offset", _ref = "inout", _optional = true }\n'
        ))
        self.assertIn("  Status move(const Offset& src, Offset* dst = nullptr) {\n", text)
        self.assertIn("    return Status(xy_move(handle_, &src, dst));\n", text)


class OptionalParam(unittest.TestCase):
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


class Validate(unittest.TestCase):
    def validate(self, text: str) -> list[str]:
        return emit_binding_cpp.validate(load(text))

    def test_cpp_keyword_as_name(self) -> None:
        for text, message in (
            (mutate(FIXTURE, "unit = ", "class = "), "wrapper: function.open_port.class: 'class' is a C++ keyword"),
            (mutate(FIXTURE, "count = { _type", "template = { _type"), "wrapper: struct.stats.template: 'template' is a C++ keyword"),
            (FIXTURE + '\n[function.new]\n_return = "status"\n', "wrapper: function.new: 'new' is a C++ keyword"),
        ):
            with self.subTest(message=message):
                self.assertIn(message, self.validate(text))

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

    def test_parameters_no_class_renders_are_not_refused(self) -> None:
        # spend has no class; send's first parameter is the handle the object holds
        for needle, old in (('htoken = "token"', "htoken"), ('[function.send]\n_return = "status"\nhport = ', "hport")):
            for name in ("result", "status", "handle", "handle_", "xy_send", "Stats"):
                with self.subTest(needle=needle, name=name):
                    self.assertEqual(self.validate(mutate(FIXTURE, needle, needle.replace(old, name))), [])

    def test_a_parameter_named_like_a_c_type_is_refused_wherever_it_is_as_the_header_refuses_it(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'htoken = "token"', 'xy_status = "token"')),
            ["wrapper: function.spend.xy_status: 'xy_status' is a name the generated code uses"],
        )

    def test_rendered_names_are_refused_as_parameters(self) -> None:
        boxed = FIXTURE + '\n[boxed_scalar.offset]\n_base_type = "u64"\n'
        for name in ("xy_send", "xy_port", "xy_status", "Port", "Stats", "Status", "uint32_t", "xy_offset", "Offset"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(mutate(boxed, 'unit = "u32"', f'{name} = "u32"')),
                    [f"wrapper: function.open_port.{name}: '{name}' is a name the generated code uses"],
                )

    def test_rendered_names_are_refused_as_methods(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "[function.send]", "[function.Stats]")),
            ["wrapper: function.Stats: 'Stats' is a name the generated code uses"],
        )

    def test_member_collision(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "[function.send]", "[function.release]")),
            ["wrapper: class Port: release would be defined more than once, by the class's own member and function.release"],
        )
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'generation = { _type = "u32", _ref = "out" }', 'send = { _type = "u32", _ref = "out" }')),
            ["wrapper: class Port: send would be defined more than once, by function.send and function.open_port.send"],
        )

    def test_release_is_a_method_name_when_no_release_is_generated(self) -> None:
        text = mutate(mutate(FIXTURE, '_dtor = "destroy_port"\n', ""), "[function.send]", "[function.release]")
        self.assertEqual(self.validate(text), [])

    def test_enum_class_entry_collision(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "ok = 0\n", "ok = 0\nerr__busy = 3\n")),
            ["wrapper: enum class Status: ErrBusy would be defined more than once, by typed_const.status.err__busy and "
             "typed_const.status.err_busy"],
        )

    def test_class_collision(self) -> None:
        self.assertEqual(
            self.validate(mutate(KITCHEN_SINK, '_class = "data_link"', '_class = "port"')),
            ["wrapper: namespace xy: Port would be defined more than once, by opaque_ref.port._class and "
             "opaque_ref.link._class"],
        )

    def test_namespace_collision(self) -> None:
        text = mutate(FIXTURE, "[[untyped_const]]\n", "[[untyped_const]]\nx = 1\n") + '\n[struct.x]\nv = "u32"\n'
        self.assertEqual(
            self.validate(text), ["wrapper: namespace xy: X would be defined more than once, by untyped_const.x and struct.x"]
        )

    def test_boxed_scalar_alias_is_in_the_namespace_list(self) -> None:
        text = FIXTURE + '\n[boxed_scalar.offset]\n_base_type = "u64"\n\n[struct.Offset]\nv = "u32"\n'
        self.assertEqual(
            self.validate(text),
            ["wrapper: namespace xy: Offset would be defined more than once, by boxed_scalar.offset and struct.Offset"],
        )

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

    def test_switch_names_the_last_entry_of_a_plain_group_shared_value(self) -> None:
        text = wrapper(mutate(KITCHEN_SINK, "extra = 4\n", "extra = 16\n"))
        self.assertIn('    case EXTRA: return "EXTRA";\n', text)
        self.assertNotIn("case MAX_UNITS:", text)
        self.assertIn('return "UNKNOWN";', text)
        self.assertIn('    case Status::ErrBusy: return "ERR_BUSY";\n', text)
        self.assertIn('return "UNKNOWN_STATUS";', text)


if __name__ == "__main__":
    unittest.main()
