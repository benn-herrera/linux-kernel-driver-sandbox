# ARCHITECTURE – api_gen

How this implementation meets SPEC.md. Standard-library Python, 3.11 or later for `tomllib`, run inside the build container; where it runs and what consumes its output is in the root ARCHITECTURE.md, "API generation".

## Shape

One pass, three stages, no state between runs:

```
definition ──load──▶ Api (frozen dataclasses) ──every emitter's validate──▶ emitters ──▶ files
```

- `model.py`: `load()` reads the TOML and `from_dict()` turns it into an `Api`. Every language-independent rule in SPEC.md "The definition" is enforced here: identifier syntax, no leading `_` on a name, uniqueness, ranges, references and lifecycle shape. Failures raise `DefinitionError` with a message that names the table and key; the loader stops at the first.
- `naming.py`: every SPEC.md "Naming" rule as a pure function of namespace and name, and `BUILTIN_C_TYPES`, the one map from a builtin type to its C spelling that the model and every emitter read. Emitters never build a generated name by string concatenation of their own.
- `emit_c.py`, `emit_cpp_wrapper.py`, `emit_lua.py`, `emit_cpp_stub.py`: one module per output, each exposing `validate(api)`, which returns every objection that output has as a message prefixed with the output's name (`header:`, `wrapper:`, `lua:`, `stub:`), and one emit function taking the `Api` and returning the file's text. A language's facts live in its emitter: its keyword table and whatever it alone would refuse. An emit function assumes its `validate` returned nothing and does not check again. They share the model and `naming` and nothing else, except that the Lua emitter calls `emit_c.cdef()`, so the FFI declarations and the header are one rendering of the same structs and functions, and the other emitters call `emit_c.c_type()`, `param_type()` and `c_params()` so every signature matches the header's; `c_params()` is the one place a `memory` parameter becomes its pointer and count pair.
- `__main__.py`: the command line. Parses arguments, loads, runs every emitter's `validate` and reports every objection at once, one line each, then runs every emitter in memory and writes, so a failing definition leaves no partial output. `output_paths()` is the one function that names the outputs; generation and `gendeps` both call it. It always writes; whether it runs at all is make's decision, from the definition's mtime. Its `gendeps` mode prints the make rules `exercises/gen.mk` includes, from the one function that names the outputs, so the naming rule has a single home and the build file carries none of it.

## The model

`Api` is a frozen dataclass tree whose every item is a `Node`, a keyword-only base carrying `name` and `docstring`: `Group` of `BitConst`, of plain constants as `EnumEntry`, or of `StringConst`; `TypedConst` of `EnumEntry`; `OpaqueRef`; `Struct` of `Field`; `Function` of `Param`. `Api` itself and its optional `DriverData` are not nodes. Tuples throughout, in document order. Each of the three untyped-constant kinds (bit, plain, string) is an array of `Group`s, each carrying a docstring and a base type (`None` for a string group), for the emitters that render one block per group; a group has no name in the definition, so its `name` is where it is, `untyped_const[0]`; `Api.bit_consts`, `Api.consts` and `Api.string_consts` are every entry across a kind's groups in order, for everything that treats constants one by one: literal values, composition, uniqueness, pins. A composed entry (a list of terms, each an earlier same-table entry or a literal integer) carries both its resolved `value` and its `parts` exactly as written, since the header renders a sum symbolically from `parts` while every other emitter uses `value` directly; the loader refuses a bit-group sum whose terms share a bit. `Api.kind()` answers the one question every emitter asks, which category a type name belongs to, from the validated tree rather than by re-checking. `Api.names()` lists every name the definition gives with where it is written, so each emitter's `validate` checks its own keywords over one walk of the tree.

Normalisation happens on the way in. A described item's `_` properties are split from its members first, so no member check ever sees a property. `_attributes()` turns a naked value into the table it is sugar for, so a bare type string and a `{ _type, ... }` table become the same `Param` or `Field`, and a bare integer and a `{ _value, _format, _docstring }` table the same `EnumEntry`; `tomllib` already makes a nested `[a.b.c]` table and an inline one the same dict. `Param.ref` is `None` or one of `in`, `out`, `inout`; `Param.count_type` is set for `memory` only. Emitters see one shape.

Order is document order because `tomllib` builds insertion-ordered dicts, a guarantee Python makes since 3.7 that the TOML specification does not. The loader's docstring states the reliance; it is the one place the project depends on it.

## Emitters

- **Header** (`emit_c.header()`): `validate()` refuses a C keyword as any name. Renders the blocks in SPEC.md order. `declarations()` renders opaque refs, structs and functions and takes the function prefix as an argument, so the header passes `NS_API ` and the cdef passes nothing, and `constants=False` for the cdef. Type mapping is `c_type()` and `param_type()`. The ABI pins are one trailing `#if defined(NS_IMPL)` block from `DriverData`, includes and `static_assert` lines, after every constant they name; `cdef()` does not render it.
- **Lua module** (`emit_lua.module()`): `_constant_sections()` renders every constant from the model's already-resolved `value` — a composed entry's sum, overlap-checked for a bit group, is computed once in `model.py`, not recomputed here — so the numbers come from the model and not from the FFI. `_class()` builds one class per opaque ref that declares a `_ctor`, from the `_ctor`, `_dtor` and `_class` the definition states; nothing about the class is inferred from names or shapes. `_marshal()` turns a parameter list into four lists at once: the Lua arguments, the C call arguments, the cdata allocations for non-memory reference parameters (copied in from the argument for `in` and `inout`, zeroed for `out`), and the values returned for `out` and `inout`; a `memory` parameter is a Lua string — `in` passed straight through with its length as the count, `out` and `inout` each allocated into a buffer that is returned as a string via `ffi.string`. The constructor uses the same arguments, call and allocations. `validate()` refuses a Lua keyword as any name, a parameter named like a local the generated code binds (`self`, `result`, `lib`, `M`, `ffi`, `indent`), a member that would collide with `new`, `_handle`, a method or a cached `out`, and a constant whose Lua name equals a class name.
- **C++ wrapper** (`emit_cpp_wrapper.wrapper()`): `validate()` refuses a C++ keyword as any name, from `CPP_KEYWORDS`, which holds the C keywords C++ shares since the wrapper includes the header, and a name defined twice in the namespace, an enum class or a class.
- **Stub** (`emit_cpp_stub.stub()`): `validate()` refuses a C++ keyword from the same `CPP_KEYWORDS`, and a return enum with no nonzero entry, since the stub has no failure result to return.

## What the emitters cannot express

- `_optional` is documentation. C has no expression for it and the Lua constructor allocates the struct regardless.
- The spelling of numbers as written. `tomllib` yields integers, so the definition says `_format = "hex"` where it wants hex; without it a value is decimal whatever the file said.

## Tests

`tests/test_model.py`, `tests/test_header.py`, `tests/test_lua.py`, `tests/test_cpp_wrapper.py`, `tests/test_cpp_stub.py` and `tests/test_cli.py` cover the generator's outputs by name — the loader's rules, the C header, the Lua module, the C++ wrapper, the C++ stub, each emitter's `validate` in its own file, and generation plus `gendeps` — standard `unittest` over a small fixture definition in a namespace of its own, so a test failure is about the generator and not about `tiny_compute`; each SPEC.md contract line has a test, and a line without one is a gap to close; `just api-gen-test` runs them in the container; `tests/test_compiled.py` compiles the header as C and C++, builds and runs the fixture's fake library under the C++ consumer and the Lua module under `luajit`, drives the `gendeps` fragment through `make -n`, and round-trips every exercise's definition, running only inside the build container (`/work/vdev` present) and skipping elsewhere; `tests/support.py` is the home of `FIXTURE`, `KITCHEN_SINK`, `MINIMAL` and the helpers.

The end-to-end check is the project's own loop: `just test` generates from the real definition, builds the library against the generated header with the pins active, builds the test program, and runs the Lua test through the generated module in the guest.

## Extension points

- A new output is a new `emit_*.py` taking the `Api`, plus one call in `__main__.py` and one path under the output directory that mirrors where it will be staged. `emit_cpp_stub.py` and `emit_cpp_wrapper.py` are the worked examples; a Rust stub is the next of that shape.
- A per-API hooks module beside the definition is reserved for peculiarities. Its interface is deliberately undefined until the first real case shows what it needs; the model is plain data so a hook can adjust it without the generator knowing why.

## On deck

- `_gen_name` on an entry: overrides the generated name where it must begin with `_`, which the naming rule otherwise forbids because a leading underscore marks metadata. Not needed yet.
