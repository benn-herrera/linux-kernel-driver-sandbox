import re
import unittest

from api_gen import emit_c, emit_cpp_stub
from api_gen.tests.support import FIXTURE, KITCHEN_SINK, load, mutate, param_lists


def stub(text: str = FIXTURE) -> str:
    return emit_cpp_stub.stub(load(text), source_name="xy_api.adef.toml", stem="xy_api")


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
        header = param_lists(emit_c.header(api, source_name="x"), r"XY_API xy_status ")
        definitions = param_lists(stub(KITCHEN_SINK), r"XY_API xy_status ")
        self.assertEqual(list(definitions), [f.name for f in api.functions])
        self.assertEqual(definitions, header)

    def test_every_body_returns_default_initialized(self) -> None:
        bodies = re.findall(
            r"\{\n((?:  \(void\)\w+;\n)*  // replace: not implemented\n  return \{\};\n)\}", self.text
        )
        self.assertEqual(len(bodies), len(load().functions))


class Validate(unittest.TestCase):
    def test_kitchen_sink_has_no_objection(self) -> None:
        self.assertEqual(emit_cpp_stub.validate(load(KITCHEN_SINK)), [])

    def test_cpp_keyword_as_name(self) -> None:
        self.assertEqual(
            emit_cpp_stub.validate(load(mutate(FIXTURE, "unit = ", "class = "))),
            ["stub: function.open_port.class: 'class' is a C++ keyword"],
        )


if __name__ == "__main__":
    unittest.main()
