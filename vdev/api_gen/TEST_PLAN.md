# TEST_PLAN – api_gen

Execution plan for the generator's test suite. Every batch ends green under `just api-gen-test-vdev`; on the host the compiled module reports skips and nothing fails. Batches are disjoint in the files they own; the pairs that may run in parallel are named. Fixture text and support code live in `tests/support.py`; hand-written compile and run targets live beside it and are not collected by `unittest discover` (pattern `test*.py`).

## Fixtures (introduced by B1 in `tests/support.py`)

- `FIXTURE`: the current text of `test_api_gen.py:13-74`, moved verbatim.
- `KITCHEN_SINK`: `FIXTURE` plus, in these places: `feat_all = ["feat_ab"]` after `feat_ab`; `neg = { value = -5, format = "hex" }` under `[untyped_const]`; `err_again = 9` and `err_unsupported = 12` after `err_other`; `[typed_const.mode]` with `fine = 0`, `slow = 1`; `docstring = "a port"` on `[opaque_ref.port]`; `[opaque_ref.link]` with `ctor = "open_link"`, `class = "data_link"`, no dtor; `docstring = "counters"` on `[struct.stats]`; `[struct.wrap]` with `inner = "stats"`, `n = "u32"`; ctor `open_port` gains `pwrap = { type = "wrap", outref = true }`; functions `recv` (`hport`, `pdst = { type = "memory", outref = true, size = "n" }`, `n = "u32"`), `configure` (`hport`, `cfg = { type = "stats", inref = true }`, `limit = { type = "u32", inref = true }`, `mode = "mode"`, `who = "token"`), `stats_of` (`hport`, `out = { type = "stats", outref = true }`, `pcount = { type = "u32", outref = true }`, `plink = { type = "link", outref = true }`), `open_link` (`plink = { type = "link", outref = true }`), `reset` (no parameters). All return `status`, so `error_to_str` stays present.
- `MINIMAL`: `[general]\nnamespace = "xy"\nversion = [0,0,0,1]\n` (today inline at `test_model.py:47`).
- Helpers: `load(text=FIXTURE)`; `mutate(text, needle, replacement)` asserting `needle in text` before replacing; `param_lists(text, pattern)` moved from `test_cpp_stub.py:23-25`; `run_main(argv) -> (code, stdout, stderr)`; `expected_constants(api) -> dict[str, int | str]` computing every Lua/C++ constant name and value from the model independently of the emitters (bit values by shift and OR over `parts`, keys upper-cased, version via `version_value()`); `IN_CONTAINER = Path("/work/vdev").is_dir()`; `container_only = unittest.skipUnless(IN_CONTAINER, "compiled and executed checks run only in the build container; run `just api-gen-test-vdev`")`; `EXERCISES = Path("/work/exercises")`.

```python
def expected_constants(api):
    bits = {}
    for c in api.bit_consts:
        bits[c.key] = (1 << c.bit if c.bit is not None else 0) | functools.reduce(operator.or_, (bits[p] for p in c.parts), 0)
    out = {"API_VERSION": api.version_value()}
    out |= {c.key.upper(): bits[c.key] for c in api.bit_consts}
    out |= {c.key.upper(): c.value for c in api.consts}
    out |= {e.key.upper(): e.value for t in api.typed_consts for e in t.entries}
    out |= {c.key.upper(): c.value for c in api.string_consts}
    return out
```

## B1 — compiled and executed checks

Owns: `tests/support.py` (new), `tests/test_compiled.py` (new), `tests/fake_xy.cpp`, `tests/check_xy.lua`, `tests/consumer_xy.cpp`, `tests/nodiscard_xy.cpp` (new), and lines 13-78 of `tests/test_api_gen.py` (replace the `FIXTURE` literal and `load` with `from api_gen.tests.support import FIXTURE, load`; the three other files keep importing them through `test_api_gen` until B4).

Runs in parallel with B2. `support.run_main` mocks `sys.argv` in this batch; B5 switches its body to `main(argv)`.

`test_compiled.py` is `@container_only` at every class; `setUpModule` returns immediately when not `IN_CONTAINER`, otherwise fails (not skips) if `clang`, `clang++`, `luajit` or `make` is missing from `PATH`, then builds once into a module-level `TemporaryDirectory` removed in `tearDownModule`:

1. Write `KITCHEN_SINK` to `<tmp>/xy_api.adef.toml`; `run_main([str(definition), "--generated", "<tmp>/generated", "--exercise", "xy"])` returns 0. `INC = <tmp>/generated/include/xy`.
2. Write `<tmp>/xy/driver/xy_ioctl.h` = `#define XYD_FEAT_A 1\n`; write `<tmp>/bad/xy/driver/xy_ioctl.h` = `#define XYD_FEAT_A 2\n`.
3. Write `<tmp>/values.c`: `#include "xy_api.h"` then one `_Static_assert(XY_<KEY> == (<value>), "XY_<KEY>");` per integer entry of `expected_constants(load(KITCHEN_SINK))` and one `_Static_assert(sizeof(XY_<KEY>) == <len+1>, "XY_<KEY>");` per string entry, then `int main(void) { return 0; }`.
4. `clang++ -std=c++20 -shared -fPIC -Wall -Wextra -Werror -I<INC> -o <tmp>/libxy.so tests/fake_xy.cpp`.
5. `clang++ -std=c++20 -Wall -Wextra -Wshadow -Werror -I<INC> -o <tmp>/consumer tests/consumer_xy.cpp -L<tmp> -lxy -Wl,-rpath,<tmp>`.

Common C flags `CFLAGS = ["-std=c17", "-fsyntax-only", "-Wall", "-Wextra", "-Werror"]` (the `.c` flags of `exercises/cpp.mk:33-34` plus `-Werror`). If `values.c` fails only on the string constants under these flags, stop and report it as a generator finding against SPEC.md "the C header" (string constants are `static const char[]`); do not drop flags.

Tests, each asserting `returncode == 0` with `stderr` as the failure message unless stated:

- `HeaderC.test_consumer_translation_unit_compiles`: `clang -x c *CFLAGS -I<INC> <tmp>/values.c`.
- `HeaderC.test_implementation_translation_unit_compiles_with_pins`: same plus `-DXY_IMPL -I<tmp>`.
- `HeaderC.test_constant_values_equal_the_model` is the same compile as the first test; name it so and make the values TU the one it compiles (the two tests above share one invocation each; a failing static_assert names its constant in stderr).
- `Stub.test_compiles_against_its_header_with_pins_active`: `clang++ --std=c++20 -fsyntax-only -Wall -Wextra -Werror -I<INC> -I<tmp> <tmp>/generated/stub/xy_api.cpp`.
- `Stub.test_pin_mismatch_fails_the_implementation_build`: same with `-I<tmp>/bad`; assert `returncode != 0` and `"XY_FEAT_A must match XYD_FEAT_A" in stderr`.
- `Wrapper.test_consumer_builds_and_runs`: `subprocess.run([<tmp>/consumer])` returns 0 (the binary's nonzero exit codes are enumerated in `consumer_xy.cpp`; assert with `f"consumer exit {code}"`).
- `Wrapper.test_discarded_result_is_a_compile_error`: `clang++ --std=c++20 -fsyntax-only -Werror=unused-result -I<INC> tests/nodiscard_xy.cpp` returns nonzero and `"unused-result" in stderr`.
- `Wrapper.test_compiles_with_a_ctor_parameter_named_status`: generate header and wrapper from `mutate(FIXTURE, 'unit = "u32"', 'status = "u32"')` into `<tmp>/status/`, write a TU `#include "xy_api.hpp"\nint main() { return xy::Port::create(1) ? 0 : 1; }`, `clang++ --std=c++20 -fsyntax-only -Wall -Wextra -Wshadow -Werror` returns 0.
- `Lua.test_module_byte_compiles`: `luajit -bl <tmp>/generated/binding/xy_api.lua` returns 0.
- `Lua.test_module_runs_against_the_fake_library`: `subprocess.run(["luajit", "tests/check_xy.lua", "<tmp>/generated/binding/xy_api.lua"], env={**os.environ, "LD_LIBRARY_PATH": "<tmp>"})` returns 0; parse stdout lines `NAME=value` into `{name: int(value) if value.lstrip("-").isdigit() else value}` and `assertEqual` to `expected_constants(load(KITCHEN_SINK))`.
- `Gendeps.test_fragment_drives_gnu_make`: in a fresh tmp dir, touch `xy_api.adef.toml`, write `frag.mk` = stdout of `run_main(["gendeps", "xy_api.adef.toml"])`, write `Makefile` = `GEN := OUTDIR\nBASE := xy\nAPI_GEN := /pkg\ninclude frag.mk\nall: $(GENERATED)\n`; `make -n -f Makefile all` returns 0 and its stdout contains `PYTHONPATH=/pkg` and `python3 -m api_gen xy_api.adef.toml --generated OUTDIR --exercise xy`.
- `RealDefinition.test_every_exercise_definition_round_trips`: `skipUnless(EXERCISES.is_dir())` with the container message; for each `api_def` directory under `EXERCISES.glob("*/userspace/api_def")` (a `subTest` per exercise): exactly one `*.adef.toml` in it; generation returns 0 into a tmp dir with `--exercise <name>`; stub compiles as above with `-I/work/exercises` (real pins against the real driver header); a TU `#include "<stem>.hpp"\nint main() { return 0; }` compiles `-fsyntax-only -Wall -Wextra -Werror`; `luajit -bl` of the module returns 0. No content assertions.

`fake_xy.cpp` (hand-written against `KITCHEN_SINK`'s header, `#include "xy_api.h"` with `XY_IMPL` defined around it, `extern "C"` via the header's macro): a static table of 4 port slots `{ uint32_t unit; bool open; }`; `xy_open_port` returns `XY_ERR_BUSY` when `unit == 99` or no slot is free, else marks a slot, sets `*pport` to it, `pstats->count = unit`, `pstats->bytes = 1ULL << 40` (skipped when `pstats` is null), `*generation = 7`, `pwrap->inner = *pstats`, `pwrap->n = 11`; `xy_destroy_port` returns `XY_ERR_OTHER` for null, calls `abort()` for a non-null handle whose slot is not open (a finalizer firing after an explicit release), else closes the slot and returns `XY_OK`; `xy_send` returns `XY_OK` iff `buf != nullptr && len == 4`, else `XY_ERR_BUSY`; `xy_recv` fills `n` bytes with `'r'` and sets byte 2 to `'\0'` when `n > 2`; `xy_configure` returns `XY_OK` iff `cfg->count == 5 && *limit == 6 && mode == XY_SLOW && who == nullptr`; `xy_stats_of` sets `out->count = 42`, `*pcount = 43`, `*plink` to a static `xy_link_opaque`; `xy_open_link` sets `*plink` to the same; `xy_spend` and `xy_reset` return `XY_OK`. Every unused parameter is voided so `-Wextra -Werror` holds.

`check_xy.lua` (`local M = dofile(arg[1])`, `local ffi = require("ffi")`; every check is an `assert`, so a failure is a nonzero exit naming the line): print `k=v` for every `M` key whose value is a number (`string.format("%d", v)`) or string; `M.status_to_str(9) == "ERR_AGAIN"`; `M.error_to_str == M.status_to_str`; `M.mode_to_str(1) == "SLOW"`; `M.Token == nil`; `M.raw.spend` and `M.raw.reset` are functions; `M.Port.new(99)` returns `nil, M.ERR_BUSY`; `p = M.Port.new(3)`; `p.pstats.count == 3`, `type(p.pstats.count) == "number"`, `p.pstats.bytes == 1099511627776ULL`, `type(p.pstats.bytes) == "cdata"`, `p.generation == 7`, `p.pwrap.inner.count == 3`, `p.pwrap.n == 11`; `p:send("abcd") == true`; `select(2, p:send("abc")) == M.ERR_BUSY`; `p:recv(5) == "rr\0rr"` and `#p:recv(5) == 5`; `p:configure({count = 5, bytes = 0}, 6, M.SLOW, nil) == true` and again with `ffi.new("xy_stats", {count = 5})`; `out, count, link = p:stats_of()` gives `out.count == 42`, `count == 43`, `link ~= nil`, and a fourth return of `nil`; `p:destroy_port() == true`; second `p:destroy_port()` returns `nil, M.ERR_OTHER`; `pcall(p.send, p, "abcd") == false`; `M.DataLink.new()` returns an object with `_handle ~= nil`; four `M.Port.new(i)` results dropped, `collectgarbage("collect")` twice, then `M.Port.new(1)` succeeds (the finalizers freed the slots).

`consumer_xy.cpp` (`#include "xy_api.hpp"`, `<cstring>`, `<type_traits>`, `<utility>`): static asserts `!std::is_copy_constructible_v<xy::Port>`, `!std::is_copy_assignable_v<xy::Port>`, `std::is_nothrow_move_constructible_v<xy::Port>`, `std::is_nothrow_move_assignable_v<xy::Port>`, `std::is_same_v<xy::Stats, xy_stats>`, `std::is_same_v<xy::Wrap, xy_wrap>`, `std::is_same_v<std::underlying_type_t<xy::Status>, int32_t>`, `int32_t(xy::Status::ErrBusy) == XY_ERR_BUSY`, `int32_t(xy::Mode::Slow) == XY_SLOW`, `xy::FEAT_ALL == XY_FEAT_ALL`, `xy::API_VERSION == XY_API_VERSION`, `int32_t(xy::NEG) == XY_NEG`. `main` returns a distinct nonzero code per failed step: `create(99, &r)` is falsy with `r == ErrBusy` and `strcmp(to_string(r), "ERR_AGAIN") == 0`; `port = create(3)` truthy with `pstats().count == 3`, `generation() == 7`, `pwrap().n == 11`; `send(buf, 4) == Ok` and `send(buf, 3) == ErrBusy`; `recv(out, 5) == Ok` with `out[2] == 0`; `configure(cfg, limit, xy::Mode::Slow, nullptr) == Ok` with `cfg.count = 5`, `limit = 6`; `stats_of(st, c, l) == Ok` with `st.count == 42`, `c == 43`, `l != nullptr`; `xy::Port moved = std::move(port)` leaves `port` falsy and `moved` truthy; `other = create(4); other = std::move(moved)` leaves `moved` falsy, `other.generation() == 7`; `other.release() == Ok`, `!other`, `other.release() == ErrOther`; a block creating four ports exits and `create(1)` afterwards is truthy (destructors released the slots); `strcmp(xy::PRODUCT, "xy widget") == 0`; `xy::DataLink::create()` is truthy.

`nodiscard_xy.cpp`: `#include "xy_api.hpp"\nint main() { auto p = xy::Port::create(1); p.send(nullptr, 0); return 0; }`.

Green before B3: `just api-gen-test-vdev` passes with every `test_compiled.py` test run (none skipped) in the container.

## B2 — source changes

Owns: `__main__.py`, `model.py`, `emit_lua.py`, `emit_cpp_wrapper.py`, `SPEC.md`, `ARCHITECTURE.md` (the "Emitters" bullet only), `tests/test_model.py` (one added test). Runs in parallel with B1.

- `__main__.py`: `def main(argv: list[str] | None = None) -> int:` with `argv = sys.argv[1:] if argv is None else argv`; the `__main__` guard unchanged.
- `model.py` `_check_lifecycles`: after the ctor check, `memory = next((p for p in ctor.params if p.outref and p.type == "memory"), None)`; if set, `raise DefinitionError(f"{where}.ctor: function.{ctor.name}.{memory.name}: a constructor cannot cache a memory outref")`. Delete the `memory` lookup and raise in `emit_lua.py` (`_constructor`) and `emit_cpp_wrapper.py` (the class emitter).
- `SPEC.md` "Rules a definition must satisfy" gains one item: `A ctor has no memory outref: the bindings cache every other outref of the ctor on the object, and a buffer has no owner there.`
- `ARCHITECTURE.md` "Emitters", Lua bullet: remove `a constructor caching a `memory` outref,` from the list of what the emitter refuses.
- `tests/test_model.py`: add `test_ctor_cannot_cache_a_memory_outref`: `assert_error(FIXTURE.replace('generation = { type = "u32", outref = true }', 'generation = { type = "u32", outref = true }\nblob = { type = "memory", outref = true, size = "unit" }'), "a constructor cannot cache a memory outref")`.

Green before B3: full suite passes; `test_cpp_wrapper.test_ctor_memory_outref_is_an_error` still passes (same message fragment, now raised by the loader).

## B3a — conversions: header and Lua

Owns: `tests/test_api_gen.py` (classes `Header`, `Lua`, `Main`, `Gendeps`). Runs in parallel with B3b. Starts after B1 and B2 are green. Uses `KITCHEN_SINK` where a feature is not in `FIXTURE`.

Header — delete `test_declarations`, `test_untyped_and_string_constants`, `test_field_comment_alignment`; trim `test_abi_pins_present_with_driver_data` to the guard count, the two `# include` lines and `re.search(r"static_assert\(XY_FEAT_A == XYD_FEAT_A, \"[^\"]+\"\);", block)`; add:

- `test_type_mapping_follows_the_spec_table`: over `emit_c.param_type(api, model.Param(name="p", type=t, outref=o, inref=i, nullsafe=False, size="n" if t == "memory" else None, docstring=None))` for the rows `("u32",F,F)→"uint32_t"`, `("u64",F,F)→"uint64_t"`, `("status",F,F)→"xy_status"`, `("stats",F,F)→"xy_stats"`, `("port",F,F)→"xy_port"`, `("stats",inref)→"const xy_stats*"`, `("stats",outref)→"xy_stats*"`, `("u32",outref)→"uint32_t*"`, `("u32",inref)→"const uint32_t*"`, `("memory",inref)→"const void*"`, `("memory",outref)→"void*"`.
- `test_functions_declared_in_document_order_with_parameters_in_order`: `decls = param_lists(header, r"XY_API xy_status ")`; `list(decls) == [f.name for f in api.functions]`; for each function, `[s.rsplit(" ", 1)[1] for s in decls[f.name].split(", ")] == [p.name for p in f.params]` when the list is not `"void"`, and `decls[f.name] == "void"` when `f.params` is empty (KITCHEN_SINK `reset`).
- `test_bit_constants_use_the_spec_spelling` (KITCHEN_SINK): `re.search(r"XY_FEAT_B = \(1u << 3\)", header)`, `"XY_FEAT_AB = XY_FEAT_A | XY_FEAT_B" in header`, `"XY_FEAT_ALL = XY_FEAT_AB" in header`.
- `test_constant_blocks_precede_types_in_spec_order`: indices of `"XY_API_VERSION"`, `"XY_FEAT_A ="`, `"XY_MAX_UNITS"`, `"enum xy_status"`, `"static const char XY_PRODUCT"`, `"struct xy_port_opaque;"`, `"struct xy_stats {"`, `"XY_API xy_status xy_open_port("` strictly increase.
- `test_docstrings_placed_per_spec`: with `lines = header.splitlines()`, the line before `enum xy_status {` is `/* call outcome */`; the line containing `XY_ERR_BUSY = 9` contains `/* try later */`; the line containing `uint32_t count;` contains `/* items seen */`; the line before the `xy_send(` declaration contains `buf: bytes to send`; the line before the `xy_destroy_port(` declaration is `/* release the port */`.

Lua — delete `test_module_surface`, `test_dtor_is_an_explicit_release_method`, `test_method_asserts_handle_is_live`, `test_constructor_caches_every_outref`, `test_inref_struct_is_copied_into_cdata`, `test_struct_outref_of_method_is_a_table`, `test_method_doc_lines`, `test_nested_struct_is_copied`, `test_outref_memory_method`, `test_composed_of_composed`, `test_new_returns_nil_result` (all covered by `check_xy.lua`, `values.c` and the tests below); replace `test_explicit_class_and_no_dtor` with `test_without_dtor_no_finalizer_and_dtor_is_an_ordinary_method`: text from `mutate(FIXTURE, 'dtor = "destroy_port"', 'class = "data_link"')`; `"ffi.gc" not in text`, `"function M.DataLink.new(unit)" in text`, `"function M.DataLink.destroy_port(self)" in text`, and the line after that `function` line starts with `assert(self._handle ~= nil`; add (all over `module = emit_lua.module(load(KITCHEN_SINK), ...)`, `api = load(KITCHEN_SINK)`):

- `test_loads_the_named_library`: `'ffi.load("libxy.so")' in module`.
- `test_constants_equal_the_model_values`: `found = {k: (v[1:-1] if v.startswith('"') else int(v, 0)) for k, v in re.findall(r"^M\.(\w+) = (.+)$", module, re.M)}`; `assertEqual(found, expected_constants(api))`.
- `test_module_namespace_is_unprefixed_and_direct`: `"M.XY_" not in module`, `"M.Token" not in module`, `"ffi.C." not in module`, `"tonumber(lib." not in module`.
- `test_raw_lists_every_function`: `raw = module[module.index("M.raw = {"):]`; `raw = raw[:raw.index("}")]`; `re.findall(r"^\s+(\w+) = lib\.xy_(\w+),$", raw, re.M) == [(f.name, f.name) for f in api.functions]`.
- `test_class_functions_are_new_the_methods_and_the_dtor`: `set(re.findall(r"^function M\.Port\.(\w+)\(", module, re.M)) == {"new"} | {f.name for f in api.functions if f.name != "open_port" and f.params and f.params[0].type == "port" and not (f.params[0].inref or f.params[0].outref)}`; same for `DataLink` with `open_link` and `link`.
- `test_c_calls_pass_parameters_in_definition_order`:

```python
calls = dict(re.findall(r"lib\.xy_(\w+)\(([^)]*)\)", module))
ctors = {o.ctor for o in api.opaque_refs}; dtors = {o.dtor for o in api.opaque_refs}
for fn in api.functions:
    if fn.name not in calls: continue
    sizes = {p.size: p.name for p in fn.params if p.type == "memory" and p.inref}
    expected = []
    for i, p in enumerate(fn.params):
        if i == 0 and fn.name not in ctors: expected.append("handle" if fn.name in dtors else "self._handle")
        elif p.name in sizes: expected.append(f"#{sizes[p.name]}")
        else: expected.append(p.name)
    self.assertEqual(calls[fn.name].split(", "), expected, fn.name)
self.assertEqual(set(calls), {f.name for f in api.functions if f.name in ctors or f.name in dtors or (f.params and api.kind(f.params[0].type) == "opaque" and not (f.params[0].inref or f.params[0].outref))})
```

- `test_lua_arguments_are_non_outref_parameters_minus_inref_sizes`: `sigs = dict(re.findall(r"^function M\.Port\.(\w+)\((.*)\)$", module, re.M))`; for the ctor, `sigs["new"].split(", ") == [p.name for p in ctor.params if not p.outref and p.name not in sizes]`; for each method, `sigs[f.name].split(", ") == ["self", *[p.name for p in f.params[1:] if not p.outref and p.name not in sizes]]`; for the dtor, `sigs["destroy_port"] == "self"`.
- `test_cdef_declares_exactly_the_header_functions_and_types`: `cdef = emit_c.cdef(api)`; `param_lists(cdef, r"^xy_status ")` with `re.M` equals `param_lists(emit_c.header(api, source_name="x"), r"XY_API xy_status ")` (pass the pattern through `re.compile(..., re.M)` or extend `param_lists` with a `flags` argument); every `f"typedef int32_t xy_{t.name};"` for `t in api.typed_consts` is in `cdef`; `"struct xy_port_opaque;"`, `"struct xy_link_opaque;"`, `"struct xy_stats {"`, `"struct xy_wrap {"` are in `cdef`.
- Keep `test_cdef_has_no_preprocessor_or_api_macro`, `test_constant_and_class_name_clash_is_rejected`, `test_no_error_to_str_with_two_return_enums`, `test_banner`.

Main — replace `test_writes_destination_layout_under_generated` with `test_writes_every_output_equal_to_its_emitter_and_reports_one_line`: after `run_main`, for each `relpath` in `output_paths(stem="xy_api", exercise="tiny_compute")`, `(generated / relpath).read_text() == <the matching emitter's text for load(FIXTURE) with source_name="xy_api.adef.toml", stem="xy_api", library="libxy.so">`; `stderr.count("\n") == 1` and every `str(relpath)` is in `stderr`. Split `test_library_override_and_missing` into `test_library_flag_overrides_the_definition` and `test_missing_library_exits_2_with_nothing_written` (the second also asserts `not generated.exists()`).

Gendeps — replace `test_one_definition_produces_the_expected_fragment` with `test_fragment_lists_the_output_paths_in_one_grouped_rule`: `out.splitlines()[0] == "# GENERATED by api_gen gendeps; do not edit."`; `targets = re.search(r"GENERATED := \\\n((?:  .*\\\n)*  .*)\n", out).group(1)`; `[t.strip().rstrip(" \\") for t in targets.splitlines()] == [f"$(GEN)/{p}" for p in output_paths(stem="a", exercise="$(BASE)")]`; `"$(GENERATED) &: a.adef.toml\n\t" in out`. Keep the three exit-2 tests.

Green before B4: full suite passes.

## B3b — conversions: stub and wrapper

Owns: `tests/test_cpp_stub.py`, `tests/test_cpp_wrapper.py`. Runs in parallel with B3a. Starts after B1 and B2 are green.

Stub — delete `test_every_parameter_voided`, `test_no_parameters`, `Outputs.test_gendeps_lists_the_stub`, `Outputs.test_stub_compiles_against_its_header_with_pins_active` (the `Outputs` class goes); replace `test_banner` with `"GENERATED" in first_line and "xy_api.adef.toml" in first_line`; replace `test_impl_define_include_undef_then_std_includes` with `test_preprocessor_lines_are_the_impl_guarded_include_then_the_std_headers`: `[l for l in text.splitlines() if l.startswith("#")] == ['#define XY_IMPL', '#include "xy_api.h"', '#undef XY_IMPL', '#include <cerrno>', '#include <cstdint>', '#include <cstring>']`; generalise `test_signatures_match_the_header_in_document_order` to `KITCHEN_SINK` and `[f.name for f in api.functions]`; replace the two `count(...) == 4` tests with `test_failure_result_is_err_unsupported_else_first_nonzero`:

```python
def returns(text): return dict(re.findall(r"xy_(\w+)\([^)]*\) \{.*?return (XY_\w+);", text, re.S))
self.assertEqual(returns(stub()), {f.name: "XY_ERR_BUSY" for f in load().functions})
self.assertEqual(returns(stub(KITCHEN_SINK)), {f.name: "XY_ERR_UNSUPPORTED" for f in load(KITCHEN_SINK).functions})
```

Keep `test_no_nonzero_entry_is_an_error`.

Wrapper — delete `test_constants_are_unprefixed`, `test_enum_class_over_the_c_values`, `test_to_string`, `test_to_string_duplicate_value_takes_the_later_name`, `test_struct_alias`, `test_create`, `test_create_status_local_avoids_parameter_names`, `test_cached_outrefs_are_private_with_const_accessors`, `test_move_construction`, `test_move_assignment_releases_the_current_handle_first`, `test_move_assignment_without_a_dtor_does_not_call_release`, `test_destructor_releases_a_live_handle`, `test_handle_and_bool`, `test_inref_memory_is_a_const_pointer_and_its_size_stays_in_the_signature`, `test_method_parameter_mapping`, `test_ctor_memory_outref_is_an_error`, and the whole `Outputs` class (B1's `consumer_xy.cpp`, `nodiscard_xy.cpp`, `values.c` and B2's model test cover them); replace `test_prelude` and `test_includes_nothing_else` with `test_includes_the_c_header_then_only_standard_headers`: `includes = [l for l in text.splitlines() if l.startswith("#include")]`; `includes[0] == '#include "xy_api.h"'`; every other line matches `r"#include <\w+>"`; `text.splitlines()[0]` contains `GENERATED` and `xy_api.adef.toml`; `text.rstrip().endswith("}  // namespace xy")`; and `test_no_exceptions_no_allocation`: none of `"throw"`, `"new "`, `"malloc"`, `"iostream"` in `text`. Keep `test_class_only_for_opaque_with_ctor`, `test_no_dtor_no_release`, `test_member_collision_is_an_error`, `test_namespace_collision_is_an_error`.

Green before B4: full suite passes.

## B4 — structure

Owns: every file under `tests/` and `ARCHITECTURE.md` "Tests". Sequential; starts after B3a and B3b.

- Split `test_api_gen.py` and delete it: `Header` → `tests/test_header.py` with classes `Preprocessor` (permitted lines, consumer includes), `Pins` (present, absent), `Declarations` (type mapping, function order, bit spelling, block order, docstrings); `Lua` → `tests/test_lua.py` with classes `Cdef`, `Constants`, `Classes`, `Refusals` (clash, two return enums), plus `test_functions_optional` moved from `test_model.py` as `Cdef.test_no_functions_yields_an_empty_raw_table`; `Main` and `Gendeps` → `tests/test_cli.py` with classes `Generate` and `Gendeps`; `ModelErrors` (17), `Naming`, `Model` → `tests/test_model.py`, merged into its `ModelErrors`, `Naming`, `Shape` (`test_parameter_order_is_document_order`, `test_class_defaults_to_the_name`, `test_version_value`).
- Every test file imports fixtures and helpers from `api_gen.tests.support` only.
- The four banner tests become one, `Generate.test_every_output_starts_with_a_generated_banner_naming_the_source` in `test_cli.py`: after `run_main`, the first line of each written file contains `GENERATED` and `xy_api.adef.toml`.
- Rename: `Naming.test_rules` → `test_every_spec_naming_row`; `test_new_constants_join_the_uniqueness_check` → `test_plain_and_string_constants_share_the_constant_namespace`; `test_generated_local_only_reserved_for_parameters` → `test_generated_locals_reserved_for_parameters_only`.
- `ARCHITECTURE.md` "Tests": replace the first paragraph with one naming the files by output (`test_model.py`, `test_header.py`, `test_lua.py`, `test_cpp_wrapper.py`, `test_cpp_stub.py`, `test_cli.py`), `test_compiled.py` as the module that compiles the header as C and C++, builds and runs the fixture's fake library under the C++ consumer and the Lua module under `luajit`, drives the `gendeps` fragment through `make -n`, and round-trips every exercise's definition, stating that it runs only inside the build container (`/work/vdev` present) and skips elsewhere, and `support.py` as the home of `FIXTURE`, `KITCHEN_SINK`, `MINIMAL` and the helpers. Keep the second paragraph.

Green before B5: full suite passes; `python3 -m unittest discover` in the container collects no test twice (test count equals the tally below).

## B5 — hygiene

Owns: every file under `tests/`. Sequential; starts after B4.

- `support.run_main` body becomes `code = api_gen_main.main(argv)` under `redirect_stdout`/`redirect_stderr`; remove every `mock.patch.object(sys, "argv", ...)` and the now-unused `mock`/`sys` imports.
- `test_cli.py`: every `main` invocation goes through `run_main`; `test_definition_error_exit_2_writes_nothing` asserts `stderr.startswith(f"api_gen: {definition}: ")` and `stderr.count("\n") == 1`.
- `test_compiled.py`: one `require_tools()` in `setUpModule`; no per-test `skipUnless(shutil.which(...))` remains anywhere in the suite.
- No test uses a literal count of fixture functions; `len(api.functions)` where a count is needed.

Green: full suite passes in the container with zero skips; on the host, `test_compiled.py` reports one skip per class with the container message and zero failures.

## Target structure

- `tests/support.py`: `FIXTURE`, `KITCHEN_SINK`, `MINIMAL`, `load`, `mutate`, `param_lists`, `run_main`, `expected_constants`, `IN_CONTAINER`, `container_only`, `EXERCISES`.
- `tests/fake_xy.cpp`, `tests/check_xy.lua`, `tests/consumer_xy.cpp`, `tests/nodiscard_xy.cpp`: compile and run targets for `KITCHEN_SINK`.
- `tests/test_model.py`: `ModelErrors` (every loader refusal with its message), `Naming` (the SPEC table), `Shape` (order, class default, version value).
- `tests/test_header.py`: `Preprocessor`, `Pins`, `Declarations`.
- `tests/test_lua.py`: `Cdef`, `Constants`, `Classes`, `Refusals`.
- `tests/test_cpp_wrapper.py`: `Wrapper` (includes, no exceptions or allocation, class only with ctor, no release without dtor), `Refusals`.
- `tests/test_cpp_stub.py`: `Stub` (banner, preprocessor lines, signatures equal the header, failure result, refusal).
- `tests/test_cli.py`: `Generate` (every output written and equal to its emitter, one stderr line, banners, exit 2 writes nothing, `--library` override and missing), `Gendeps` (fragment lists the output paths, exit-2 cases).
- `tests/test_compiled.py` (container only): `HeaderC`, `Stub`, `Wrapper`, `Lua`, `Gendeps`, `RealDefinition`.

## Tally of the 104 existing tests

- Survive: 57 — `test_model.py` 18; `test_api_gen.py` 33 (`ModelErrors` 17, `Naming` 1, `Model` 2, `Header` 5, `Lua` 3, `Main` 2, `Gendeps` 3); `test_cpp_stub.py` 2; `test_cpp_wrapper.py` 4.
- Convert: 14 — `Header.test_declarations`, `Header.test_untyped_and_string_constants`, `Lua.test_module_surface`, `Lua.test_explicit_class_and_no_dtor`, `Lua.test_banner`, `Main.test_writes_destination_layout_under_generated`, `Gendeps.test_one_definition_produces_the_expected_fragment`, `Stub.test_banner`, `Stub.test_impl_define_include_undef_then_std_includes`, `Stub.test_failure_is_first_nonzero_entry`, `Stub.test_failure_prefers_err_unsupported`, `Wrapper.test_prelude`, `Wrapper.test_includes_nothing_else`, `Wrapper.test_ctor_memory_outref_is_an_error`.
- Go: 33 — `Header.test_field_comment_alignment`; `Lua` 10 (`test_dtor_is_an_explicit_release_method`, `test_method_asserts_handle_is_live`, `test_constructor_caches_every_outref`, `test_inref_struct_is_copied_into_cdata`, `test_struct_outref_of_method_is_a_table`, `test_method_doc_lines`, `test_nested_struct_is_copied`, `test_outref_memory_method`, `test_composed_of_composed`, `test_new_returns_nil_result`); `test_cpp_stub.py` 4 (`test_every_parameter_voided`, `test_no_parameters`, `Outputs.test_gendeps_lists_the_stub`, `Outputs.test_stub_compiles_against_its_header_with_pins_active`); `test_cpp_wrapper.py` 18 (the fifteen text tests listed in B3b, `Outputs.test_gendeps_lists_the_wrapper`, `Outputs.test_generation_writes_the_wrapper_beside_the_header`, `Outputs.test_wrapper_compiles_for_a_consumer`).
- Added: 12 in `test_compiled.py`, 1 in `test_model.py`, 14 in `test_header.py`/`test_lua.py`/`test_cli.py` from B3a, 4 from B3b. Target size about 90 tests, 12 of them compiled or executed.
