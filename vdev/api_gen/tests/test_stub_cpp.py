import re
import unittest

from api_gen.emitters import emit_stub_cpp
from api_gen.tests.support import DOCUMENTED_FUNCTION_GROUPS, FIXTURE, KITCHEN_SINK, load, mutate


def stub(text: str = FIXTURE) -> str:
    return emit_stub_cpp.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", library=None, project="xy")


class Stub(unittest.TestCase):
    def setUp(self) -> None:
        self.text = stub()

    def test_preprocessor_lines_are_the_impl_guarded_include_then_the_std_headers(self) -> None:
        lines = [line for line in self.text.splitlines() if line.startswith("#")]
        self.assertEqual(
            lines,
            [
                "#define XY_IMPL",
                '#include "xy_api.h"',
                "#undef XY_IMPL",
                "#include <cerrno>",
                "#include <cstdint>",
                "#include <cstring>",
            ],
        )

    def test_every_body_voids_each_parameter_then_returns_default_initialized(self) -> None:
        api = load(KITCHEN_SINK)
        bodies = dict(re.findall(
            r"xy_(\w+)\([^)]*\) \{\n((?:  \(void\)\w+;\n)*)  // replace: not implemented\n  return \{\};\n\}\n",
            stub(KITCHEN_SINK),
        ))
        self.assertEqual(list(bodies), [f.name for f in api.functions])
        for fn in api.functions:
            with self.subTest(function=fn.name):
                names = [n for p in fn.params for n in ([p.name, f"{p.name}_count"] if p.type == "memory" else [p.name])]
                self.assertEqual(bodies[fn.name], "".join(f"  (void){n};\n" for n in names))


class Validate(unittest.TestCase):
    def test_cpp_keyword_as_name(self) -> None:
        self.assertEqual(
            emit_stub_cpp.validate(load(mutate(FIXTURE, "unit = ", "class = "))),
            ["stub: function.open_port.class: 'class' is a C++ keyword"],
        )

    def test_parameter_named_like_a_type_its_signatures_spell_as_the_header_refuses(self) -> None:
        self.assertEqual(
            emit_stub_cpp.validate(load(mutate(FIXTURE, 'htoken = "token"', 'uint32_t = "token"'))),
            ["stub: function.spend.uint32_t: 'uint32_t' is a name the generated code uses"],
        )



class GroupDocstring(unittest.TestCase):
    def test_a_function_groups_docstring_is_a_line_above_its_first_definition(self) -> None:
        text = stub(DOCUMENTED_FUNCTION_GROUPS)
        self.assertIn("\n// port lifecycle\nXY_API xy_status xy_open_port(", text)
        self.assertIn("\n\nXY_API xy_status xy_destroy_port(", text)
        self.assertIn("\n// traffic\nXY_API xy_status xy_send(", text)


if __name__ == "__main__":
    unittest.main()
