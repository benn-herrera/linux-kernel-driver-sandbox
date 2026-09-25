# BURNDOWN – api_gen

Fixes from the architect review of 2026-09-25, ordered for execution.
Each batch is one coder dispatch and touches functions no other batch
touches. Line numbers are as of the review and were checked against the
sources the same day; a coder re-locates by function name. Findings are
referenced by the review's labels (C1..C8 coincidences, G1..G8 gotchas,
DRY, coverage, doc). Strike items as they land.

## Batch A — `model.py` validation (plus `ModelErrors` tests, SPEC "The definition")

No batch edits `FIXTURE`; new cases use `FIXTURE + "..."` or `.replace(...)` inline, as the file already does.

**A1. DONE 2026-09-25 — One reserved-name set, enforced on every name**
- Touches: `model.py` new `RESERVED_NAMES` beside `RESERVED_KEYS` (:16); `_identifier` (:212-217).
- After: `RESERVED_NAMES` = C keywords (`auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while`) ∪ Lua keywords (`and break do else elseif end false for function goto if in local nil not or repeat return then true until while`) ∪ generated locals (`self result lib M ffi`). `_identifier` rejects with `{where}: '{name}' is a C or Lua keyword or a name the generated code binds`. Reaches params, fields, enum entries, bit consts, function/type names via the existing callers.
- Test: `test_keyword_as_name` — `FIXTURE.replace("bytes = ", "end = ")` and `.replace('unit = "u32"', 'int = "u32"')` and `FIXTURE + '\n[function.end]\nreturn = "status"\n'` each raise with "keyword or a name".
- Closes: C2, C3, DRY (two reserved sets).
- Docs: SPEC.md "Every name is a C identifier." → append "that is neither a C nor a Lua keyword nor one of `self`, `result`, `lib`, `M`, `ffi`." ARCHITECTURE.md "`_LUA_RESERVED` refuses parameter names that would shadow the generated locals (`self`, `result`, `lib`, `M`, `ffi`) or Lua keywords." becomes false — B4 rewrites it.

**A2. DONE 2026-09-25 — Generated C identifiers unique across types, opaque tags and functions**
- Touches: `model.py` `_check_unique_constants` (:461-470) → rename `_check_unique_identifiers` and extend; call at :204.
- After: one `seen` map over `naming.const_name` (constants, as now) plus `naming.type_name` for every enum/opaque/struct, `naming.opaque_struct` for every opaque, `naming.function_name` for every function. Duplicate → `{where}: C identifier {ident} already defined by {seen[ident]}`.
- Test: `test_function_named_like_a_type` — `FIXTURE + '\n[function.stats]\nreturn = "status"\n'` raises "already defined by struct.stats"; `test_struct_named_like_an_opaque_tag` — `FIXTURE + '\n[struct.port_opaque]\nx = "u32"\n'` raises "already defined by opaque_ref.port".
- Closes: C3.
- Docs: SPEC.md "Constant names are unique across the bit constants, every enum, and the version constant." → append "; the C identifiers of enums, opaque refs and their tags, structs and functions are unique together."

**A3. DONE 2026-09-25 — `size` required on `memory`; one size parameter per buffer**
- Touches: `model.py` `_function` (:409-413, :425-434).
- After: `memory` without `size` → `{pwhere}: a 'memory' parameter names its 'size' parameter`. A size parameter named by two memory params → `{where}.{p.name}.size: '{p.size}' is already the size of '{first}'`.
- Test: move `Lua.test_memory_without_size_is_rejected` (:264-267 — `load()` sits outside `assertRaises`, so after this change the old test would error rather than pass) into `ModelErrors.test_memory_needs_size`, asserting "names its 'size' parameter"; `test_size_serves_one_buffer` — `FIXTURE.replace('len = "u64"', 'len = "u64"\nbuf2 = { type = "memory", outref = true, size = "len" }')` raises "already the size of 'buf'".
- Closes: C4, coverage.
- Docs: SPEC.md "and for `memory` parameters `size`, naming the sibling parameter that holds the byte count." → "and for `memory` parameters `size` (required), naming the sibling `u32`/`u64` by-value parameter that holds the byte count; a size parameter serves one buffer." ARCHITECTURE.md "Every rule in SPEC.md 'The definition' is enforced here and nowhere else; an emitter never re-validates." becomes true for this rule.

**A4. DONE 2026-09-25 — `[function]` optional**
- Touches: `model.py` `from_dict` (:140-141, delete).
- After: a definition without `[function]` loads; `emit_lua.module` emits `M.raw = {\n}` and no `error_to_str`; `emit_c.header` emits no function block.
- Test: `test_functions_optional` — `load('[general]\nnamespace = "xy"\nversion = [0,0,0,1]\n')` succeeds; `emit_lua.module(...)` contains `M.raw = {\n}`; `emit_c.header(...)` succeeds.
- Closes: C5.
- Docs: SPEC.md "each optional unless stated" becomes true (currently false).

**A5. DONE 2026-09-25 — Return enums must have a zero entry**
- Touches: `model.py` `_function` (:395-396) or `from_dict` after functions are built.
- After: a function returning an enum with no value-0 entry → `function.{name}.return: typed_const '{returns}' has no zero-valued entry for success`.
- Test: `test_return_enum_needs_zero` — `FIXTURE.replace("ok = 0", "ok = 1")` raises "no zero-valued entry".
- Closes: the "emitter never re-validates" claim (validation currently at `emit_lua._ok_const` :97-99; B4 removes it).
- Docs: SPEC.md "`return` (a `typed_const` enum name, required)" → append "whose entries include the value 0".

**A6. DONE 2026-09-25 — Strings that land inside quotes are quote-free**
- Touches: `model.py` `from_dict` (:153-155), `_driver_data` (:444-446).
- After: `general.library` or `driver_data.header` containing `"` or `\` → `general.library must not contain '"' or '\'` / `driver_data.header must not contain '"' or '\'`.
- Test: `test_quoted_library_rejected` — `FIXTURE.replace('library = "libxy.so"', 'library = "lib\\"xy.so"')` raises "must not contain".
- Closes: G7.
- Docs: SPEC.md "`library` (the shared object file name the script binding loads)" → "(a plain file name, no quotes or backslashes)".

**A7. DONE 2026-09-25 — Enumerators fit `int`** (ruling on G1: restrict in the loader)
- Touches: `model.py` `_bit_consts` (bit index range) and the `general.version` check.
- After: a bit index outside 0..30 → `untyped_bit_const.{key}: bit index must be 0..30 (enumerators must fit int)`; a first version byte above 127 → `general.version: first byte must be 0..127 (enumerators must fit int)`.
- Test: `test_bit_index_range` (31 rejected, 30 accepted), `test_version_first_byte_range`.
- Docs: SPEC.md `[untyped_bit_const]` and `general.version` lines state the ranges.

**A8. DONE 2026-09-25 — C++ keywords reserved** (found by the wrapper work)
- Touches: `model.py` `RESERVED_NAMES`.
- After: C++ keywords that are not C keywords (`class new delete this template operator namespace public private protected virtual friend explicit constexpr nullptr true false try catch throw using typename export mutable`, and the rest of the C++20 list) are refused for every name, since every generated header is included by C++ and the wrapper spells names inside `namespace`.
- Test: `test_cpp_keyword_as_name` in `test_model.py`.
- Docs: SPEC.md "neither a C nor a Lua keyword" → "neither a C, C++ nor Lua keyword".

Batch A tests go in a new `tests/test_model.py` so batch B can run in parallel in `tests/test_api_gen.py`.

## Batch B — `emit_lua.py` class and marshalling (plus `Lua` tests, SPEC Lua section)

**B1. DONE 2026-09-25 — Non-memory `inref` marshals**
- Touches: `emit_lua.py` `_marshal` (:135-153).
- After: for `p.inref and p.type != "memory"`: Lua arg `p.name`; alloc `local {p.name} = ffi.new("{T}", {p.name})` for a struct (LuaJIT initialises from a table or copies a cdata), `local {p.name} = ffi.new("{T}[1]", {p.name})` for `u32`/`u64`/enum/opaque; call passes `p.name`. The rhs refers to the outer parameter, so no new identifier is introduced.
- Test: `test_inref_struct_is_copied_into_cdata` — `FIXTURE + '\n[function.configure]\nreturn = "status"\nhport = "port"\ncfg = { type = "stats", inref = true }\n'`: module contains `function M.XyPort.configure(self, cfg)`, `local cfg = ffi.new("xy_stats", cfg)`, `lib.xy_configure(self._handle, cfg)`; header contains `const xy_stats* cfg`.
- Closes: C1.
- Docs: SPEC.md "`outref` of a non-memory type `T` → `T*`; `memory` → …" → insert "`inref` of a non-memory `T` → `const T*`;". SPEC.md method paragraph → append "an `inref` struct is passed as a table or cdata, an `inref` scalar as a number."

**B2. DONE 2026-09-25 — Struct values are plain tables everywhere, recursively**
- Touches: `emit_lua.py` `_lua_value` (:115-118), `_marshal` rets (:152), `_constructor` (:169-177, :194-201 — drop the `cached` field split; every non-handle outref becomes `self.{p.name} = {_lua_value(...)}`).
- After: `_lua_value(api, type, expr)` returns `tonumber(expr)` for `u32`/enum, `expr` for `u64`/opaque, and for a struct a table constructor `{ f = _lua_value(api, f.type, f"{expr}.{f.name}"), ... }` recursing into nested structs. Method struct outrefs return that table, not `x[0]`.
- Test: `test_struct_outref_of_method_is_a_table` — `FIXTURE + '\n[function.stats_of]\nreturn = "status"\nhport = "port"\nout = { type = "stats", outref = true }\n'`: contains `count = tonumber(out[0].count)` and `bytes = out[0].bytes`, not `return out[0], nil`. `test_nested_struct_is_copied` — `FIXTURE.replace("[function.open_port]", '[struct.wrap]\ninner = "stats"\nn = "u32"\n\n[function.open_port]').replace('pstats = { type = "stats"', 'pstats = { type = "wrap"')`: contains `inner = {` and `count = tonumber(pstats.inner.count)`. `test_constructor_caches_every_outref` (:238-248) keeps passing.
- Closes: C6, G4.
- Docs: SPEC.md "a struct as a plain table copy of its fields (`u32` and enum fields as numbers, `u64` as cdata), a scalar as a number" → append ", nested structs copied the same way"; SPEC.md "`outref` values are returned in order after a successful call" → append ", a struct as the same plain table".

**B3. `dtor` becomes an explicit release method** — DONE 2026-09-25 (folded into the unprefixed-constants pass)
- Touches: `emit_lua.py` `_class` (:124-131), new `_dtor_method`.
- After: with `dtor`, emit `function {cls}.{dtor}(self)`: `ffi.gc(self._handle, nil)`, `local result = lib.{ns_dtor}(self._handle)`, `self._handle = nil`, then the standard `if result ~= OK then return nil, result end` / `return true, nil`. Without `dtor`, unchanged.
- Test: `test_dtor_method_disarms_gc` — module contains `function M.XyPort.destroy_port(self)`, `ffi.gc(self._handle, nil)`, `self._handle = nil`. Flip `test_module_surface` (`assertNotIn("M.XyPort.destroy_port")`) to `assertIn`. `test_explicit_class_and_no_dtor` stays.
- Closes: G6.
- Docs: SPEC.md "One method per function, other than the `ctor` and `dtor`, whose first parameter is the opaque by value" → "other than the `ctor`; the `dtor`'s method disarms the finalizer, calls it and clears `_handle`, after which the object is unusable". SPEC.md "with the `dtor` as its GC finalizer" stays true.

**B4. DONE 2026-09-25 — Remove emitter-side validation the model now owns**
- Touches: `emit_lua.py` `_LUA_RESERVED` (:7-12) delete; `_check_lua_names` (:103-108) delete and its calls at :167 and :207; `_ok_const` (:95-100) drop the `raise` (:98-99), keep the lookup; `_cdef` (:81-86) → `return f"ffi.cdef[[\n{text}]]\n"` (model bans `]]`).
- After: `emit_lua` raises `DefinitionError` only at `_constructor` :175 (memory outref in a ctor) and :179-181 (member collisions with `new`/`_handle`) — both facts only the emitter knows.
- Test: existing `Lua` tests; `test_cdef_has_no_preprocessor_or_api_macro` already assumes `[[`.
- Closes: DRY (`]]` handled twice; reserved sets); ARCHITECTURE.md "an emitter never re-validates" becomes true except for the two emitter-only checks.
- Docs: ARCHITECTURE.md (quoted in A1) → "The emitter refuses only what it alone knows: a constructor caching a `memory` outref, and a member that would collide with `new`, `_handle`, a method or a cached outref." ARCHITECTURE.md "`_device_class()` builds one class per opaque ref" → `_class()`.

## Batch C — `emit_c.py` (plus `Header` tests)

**C1. DONE 2026-09-25 — `cdef()` is `declarations()` without constants**
- Touches: `emit_c.py` `cdef` (:72-82), `declarations` (:85-94).
- After: `declarations(api, *, function_prefix, constants=True)`; `cdef()` = the enum typedef lines + `declarations(api, function_prefix="", constants=False)`. One block-assembly path.
- Test: existing `Header.test_declarations` and `Lua.test_cdef_has_no_preprocessor_or_api_macro`.
- Closes: DRY (cdef/declarations).
- Docs: ARCHITECTURE.md "`declarations()` renders opaque refs, structs and functions and takes the function prefix as an argument, so the header passes `NS_API ` and the cdef passes nothing." stays true; append "and `constants=False` for the cdef".

**C2. DONE 2026-09-25 — Consistent enum trailing comma**
- Touches: `emit_c.py` `_typed_enum` (:127-129) — no comma after the last entry, as `_bit_enum` (:119).
- Test: `test_declarations` expected `"  XY_ERR_OTHER = 0x7fffffff,\n};"` → `"  XY_ERR_OTHER = 0x7fffffff\n};"`.
- Closes: DRY (trailing-comma rule differs). Header becomes C89-clean too.
- Docs: none.

**C3. DONE 2026-09-25 — Header tests for the consumer include set and field alignment**
- Touches: `tests/test_api_gen.py` `Header`, new methods only.
- Test: `test_consumer_includes_only_stdint` — every `#include`/`# include` line before `#if defined(XY_IMPL)` is `#include <stdint.h>`. `test_field_comment_alignment` — `FIXTURE.replace('bytes = "u64"', 'bytes_total = { type = "u64", docstring = "d" }')`: the two `/*` in the `xy_stats` body start at the same column (the fixture's equal-width fields make the existing assertion pass by coincidence).
- Closes: coverage (SPEC.md "For a consumer, includes only `<stdint.h>`").

## Batch D — cross-file DRY helpers (functions untouched by A–C)

**D1. DONE 2026-09-25 — One version value** (ruling: the header keeps its shift expression)
- Touches: `model.py` `Api` add `version_value() -> int`; `emit_lua.py` `_version_literal` → `0x{api.version_value():08x}`; `emit_c.py` unchanged in output (it may spell the shifts from `api.version`).
- After: header `XY_API_VERSION = (0x01 << 24) | ...` as today; Lua `M.API_VERSION = 0x01020304` computed from the one helper.
- Test: `test_module_surface` unchanged; a model test that `version_value()` of `[1,2,3,4]` is `0x01020304`.
- Closes: DRY (the packing rule has one home).

**D2. DONE 2026-09-25 — One function-doc list**
- Touches: `model.py` `Function` (:85-90) add `docs() -> list[str]` (`[docstring] + ["p: doc" ...]`); `emit_c.py` `_function` (:154-155); `emit_lua.py` `_doc_lines` (:89-92).
- Test: existing `test_declarations` (`/* buf: bytes to send */`) and a new `test_method_doc_lines` asserting `-- buf: bytes to send\nfunction M.XyPort.send(`.
- Closes: DRY (doc list).
- Docs: SPEC.md "Docstrings become `/* */` comments: above an enum, struct or function, trailing an enum entry or struct field." → append "; a parameter's docstring joins its function's comment as `name: text`, and an opaque ref's docstring sits above its declaration" (currently unstated but done).

## Batch E — coverage and documents (test methods and doc lines only)

**E1. DONE 2026-09-25 — Tests for SPEC lines with none**
- Touches: `tests/test_api_gen.py`, new methods in `ModelErrors`, `Lua`, `Main`.
- `test_docstring_terminators_rejected` — `'*/'` in a docstring → "must not contain".
- `test_bit_index_range`, `test_int32_range` — `feat_a = 32`; `ok = 0x80000000`.
- `test_builtin_shadow` — `FIXTURE + '\n[struct.u32]\nx = "u64"\n'` → "shadows builtin".
- `test_constant_uniqueness` — `api_version = 5` under `[untyped_bit_const]` → "already defined by the API version constant"; `feat_a = 4` under `[typed_const.status]` → "already defined by untyped_bit_const.feat_a".
- `test_composed_of_composed` — `FIXTURE.replace('format = "hex" }\n\n[typed', 'format = "hex" }\nfeat_all = ["feat_ab"]\n\n[typed')` → `M.XY_FEAT_ALL = 9` and header `XY_FEAT_ALL = XY_FEAT_AB`.
- `test_to_str_table` — module contains `[M.XY_ERR_BUSY] = "XY_ERR_BUSY"`.
- `test_new_returns_nil_result` — contains `if result ~= M.XY_OK then\n        return nil, result` inside `new`.
- `test_outref_memory_method` — `FIXTURE + '\n[function.recv]\nreturn = "status"\nhport = "port"\npdst = { type = "memory", outref = true, size = "n" }\nn = "u32"\n'`: `function M.XyPort.recv(self, n)`, `ffi.new("uint8_t[?]", n)`, `return ffi.string(pdst, n), nil`; and `send` returns `true, nil`.
- `test_definition_error_exit_2_writes_nothing` — bad definition file → `main()` returns 2, stderr starts `api_gen: {path}: `, `generated` does not exist.
- `test_library_override_and_missing` — `--library libz.so` yields `ffi.load("libz.so")`; fixture without `library` and no flag → 2 with "pass --library".
- `test_banner` — both outputs' first line contains `GENERATED by vdev/api_gen from xy_api.adef.toml`.
- Closes: coverage.

**E2. DONE 2026-09-25 — Document lines to correct**
- ARCHITECTURE.md "They share the model and `naming` and nothing else, except that the Lua emitter calls `emit_c.cdef()`" → "…except that the Lua emitter calls `emit_c.cdef()` and `emit_c.c_type()`" (true today; `c_type` is not moving — see below).
- ARCHITECTURE.md "a bare integer or a `{ value, docstring }` table" → "`{ value, docstring, format }`".
- ARCHITECTURE.md "Covered: each validation error with its message, … the header's declarations for a two-function API" → list what E1 and A–C leave covered; drop "each".
- SPEC.md "Results and constants are plain Lua numbers; nothing the module returns needs `tonumber`." contradicts the `u64`-as-cdata rule → "Results, constants, `u32` and enum values are plain Lua numbers; `u64` values are cdata (they compare with numbers and print with a `ULL` suffix)."
- SPEC.md `<enum>_to_str` line: append "; two entries with one value map to the later name."
- SPEC.md method returns: append "; an `outref` opaque in a method is returned as the raw handle, unwrapped."
- `vdev/api_gen/__init__.py` docstring "(C header, ABI pin unit, LuaJIT module)" → "(C header with ABI pins, LuaJIT module)".
- `vdev/api_gen/README.md` "an optional stub file for the C++ implementation" — in neither SPEC "Not generated" nor the roadmap; the human decides where it lives.
- Closes: doc mismatches, G3, G5, C8.

## Batch F — implementation stub emitter (new output)

**F1. DONE 2026-09-25 — `emit_cpp_stub.py`**
- Touches: new `emit_cpp_stub.py`; `__main__.py` output paths (a third output `stub/<stem>.cpp`, listed by `gendeps` in `GENERATED` and the grouped rule); tests.
- After: `generated/stub/<stem>.cpp` holds the banner, `#define NS_IMPL` / `#include "<stem>.h"` / `#undef NS_IMPL`, `#include <cstdint>`, `<cstring>`, `<cerrno>`, and one body per function in document order: `TCDL_API tcdl_result tcdl_f(params) { (void)p; ...; /* replace: not implemented */ return <NS>_ERR_...; }` returning the enum entry named `err_unsupported` if the return enum has one, else the enum's first non-zero entry. Never staged (not under `include/` or `binding/`); the human copies it into `lib/` once when starting an implementation.
- Test: content assertions; and in `api-gen-test` (container) a `clang++ --std=c++20 -fsyntax-only -I<generated include dir> stub/<stem>.cpp` over the fixture's output proves it compiles against its header.
- Docs: SPEC.md "Outputs" gains the stub; "Not generated" keeps the real implementation; README.md's stub line becomes true. `emit_rust_stub.py` is the planned sibling.

## Batch G — header-only C++ wrapper (new output)

**G1w. DONE 2026-09-25 — `emit_cpp_wrapper.py`**
- Touches: new emitter; `__main__.py` output paths (`include/<exercise>/<stem>.hpp`, staged with the C header); tests.
- After: `namespace <ns>` with the constants as `inline constexpr`, the enums as `enum class` over the C values, a class per opaque ref with a `ctor` (`class` in UpperCamel: `Device`): move-only, the handle released by the `dtor` in the destructor, every ctor outref cached as a member (`info`), one method per function whose first parameter is the opaque by value, forwarding inline to the C function; `memory` parameters as `std::span<const std::byte>` / `std::span<std::byte>` so the `size` parameter disappears from the signature. Includes only the C header and `<span>`, `<cstddef>`, `<utility>`. Nothing to compile: header-only.
- Design point to settle at dispatch: how the constructor reports failure (a static `create` returning `std::optional<Device>` plus a result out-parameter keeps the wrapper exception-free and mirrors the Lua `nil, result` convention).
- Test: content assertions plus `clang++ --std=c++20 -fsyntax-only` in `api-gen-test` over a fixture TU that instantiates the class.
- Docs: SPEC.md "Outputs" gains the wrapper; the exercise ARCHITECTURE.md roadmap item moves to done when the test program uses it.

## Deliberately not fixed

- **G1** — ruled: restrict in the loader (A7).
- **G2 (`ffi.new("uint8_t[?]", count)` / `ffi.string(buf, count)` with an int64 cdata count).** LuaJIT's argument conversion accepts cdata integers as far as the reviewer knows; not certain. Settle in the guest with `dev:dma_from_device(0, 48ULL)`; if it errors, wrap both uses in `_marshal` in `tonumber()`.
- **`u64` returned as cdata (G3).** `tonumber` would silently truncate above 2^53; cdata is the correct carrier. SPEC sentence in E2.
- **`c_type` living in `emit_c` rather than `naming`.** Its callers in `emit_lua` sit in functions batch B rewrites; the move buys nothing the doc correction in E2 does not. Revisit only if a third emitter appears.
- **Member-collision check and the memory-outref-in-ctor refusal staying in the emitter.** They concern names and shapes only the Lua class defines; moving them makes the model know a binding's internals. ARCHITECTURE wording adjusted in B4.
- **`nullsafe` producing no output (C7).** ARCHITECTURE.md already states it is documentation; rendering it into comments is optional polish.
- **Functions whose opaque is not first being silently omitted from the class (G8).** SPEC.md covers it.
- **Ad-hoc `next(...)` lookups in `emit_lua`.** Three sites, one line each; a lookup table on `Api` is more code than it removes.
- **An enum named `error` versus the `M.error_to_str` alias.** Only bites when functions return a different enum; adding `error` to the reserved set is disproportionate. Note it in SPEC if it ever matters.
