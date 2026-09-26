import re
import unittest

from api_gen import emit_stub_cpp
from api_gen.tests.support import FIXTURE, KITCHEN_SINK, header, load, mutate, param_lists


def stub(text: str = FIXTURE) -> str:
    return emit_stub_cpp.emit(load(text), source_name="xy_api.adef.toml", stem="xy_api", library=None)


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

    def test_signatures_match_the_header_in_document_order(self) -> None:
        api = load(KITCHEN_SINK)
        declared = param_lists(header(api), r"XY_API xy_status ")
        definitions = param_lists(stub(KITCHEN_SINK), r"XY_API xy_status ")
        self.assertEqual(list(definitions), [f.name for f in api.functions])
        self.assertEqual(definitions, declared)

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
    def test_kitchen_sink_has_no_objection(self) -> None:
        self.assertEqual(emit_stub_cpp.validate(load(KITCHEN_SINK)), [])

    def test_cpp_keyword_as_name(self) -> None:
        self.assertEqual(
            emit_stub_cpp.validate(load(mutate(FIXTURE, "unit = ", "class = "))),
            ["stub: function.open_port.class: 'class' is a C++ keyword"],
        )


if __name__ == "__main__":
    unittest.main()
