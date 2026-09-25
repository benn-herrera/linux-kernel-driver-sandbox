# ARCHITECTURE – api_gen

How this implementation meets SPEC.md. Standard-library Python, 3.11 or
later for `tomllib`, run inside the build container; where it runs and
what consumes its output is in the root ARCHITECTURE.md, "API generation".

## Shape

One pass, three stages, no state between runs:

```
definition ──load/validate──▶ Api (frozen dataclasses) ──▶ emitters ──▶ files
```

- `model.py`: `load()` reads the TOML and `from_dict()` turns it into an
  `Api`. Every rule in SPEC.md "The definition" is enforced here and
  nowhere else; an emitter never re-validates. Failures raise
  `DefinitionError` with a message that names the table and key.
- `naming.py`: every SPEC.md "Naming" rule as a pure function of namespace
  and key. Emitters never build a generated name by string concatenation
  of their own.
- `emit_c.py`, `emit_lua.py`: one function per output, each taking the
  `Api` and returning the file's text. They share the model and `naming`
  and nothing else, except that the Lua emitter calls `emit_c.cdef()` so
  the FFI declarations and the header are one rendering of the same
  structs and functions.
- `__main__.py`: the command line. Parses arguments, loads, runs both
  emitters in memory, and writes only if both succeed, so a failing
  definition leaves no partial output. It always writes; whether it runs
  at all is make's decision, from the definition's mtime. Its
  `gendeps` mode prints the make rules `exercises/gen.mk` includes, from
  the one function that names the outputs, so the naming rule has a
  single home and the build file carries none of it.

## The model

`Api` is a frozen dataclass tree: `BitConst`, `TypedConst` of `EnumEntry`,
`OpaqueRef`, `Struct` of `Field`, `Function` of `Param`, and an optional
`DriverData`. Tuples throughout, in document order. `Api.kind()` answers
the one question every emitter asks, which category a type name belongs
to, from the validated tree rather than by re-checking.

Normalisation happens on the way in. The union forms SPEC.md allows, a
bare type string or an inline table, both become the same `Param` or
`Field`; a bare integer or a `{ value, docstring }` table both become the
same `EnumEntry`. Emitters see one shape.

Order is document order because `tomllib` builds insertion-ordered dicts,
a guarantee Python makes since 3.7 that the TOML specification does not.
The loader's docstring states the reliance; it is the one place the
project depends on it.

## Emitters

- **Header** (`emit_c.header()`): renders the blocks in SPEC.md order.
  `declarations()` renders opaque refs, structs and functions and takes
  the function prefix as an argument, so the header passes `NS_API ` and
  the cdef passes nothing. Type mapping is `c_type()` and `param_type()`.
  The ABI pins are one trailing `#if defined(NS_IMPL)` block from
  `DriverData`, includes and `static_assert` lines, after every constant
  they name; `cdef()` does not render it.
- **Lua module** (`emit_lua.module()`): `_constant_literals()` computes
  every value in Python, bit constants by shifting and masks by OR over
  earlier entries, so the numbers come from the model and not from the
  FFI. `_device_class()` builds one class per opaque ref that declares a
  `ctor`, from the `ctor`, `dtor` and `class` the definition states;
  nothing about the class is inferred from names or shapes.
  `_marshal()` turns a parameter list into four lists at once: the Lua
  arguments, the C call arguments, the allocations for outrefs, and the
  values returned; the `size` rule for `memory` lives there, dropping the
  count from the arguments for an inref string and passing `#name`, and
  keeping it for an outref buffer. `_LUA_RESERVED` refuses parameter names
  that would shadow the generated locals (`self`, `result`, `lib`, `M`,
  `ffi`) or Lua keywords.

## What the emitters cannot express

- `nullsafe` is documentation. C has no expression for it and the Lua
  constructor allocates the struct regardless.
- The spelling of numbers as written. `tomllib` yields integers, so the
  definition says `format = "hex"` where it wants hex; without it a value
  is decimal whatever the file said.

## Tests

`tests/test_api_gen.py`, standard `unittest` over a small fixture
definition in a namespace of its own, so a test failure is about the
generator and not about `tiny_compute`. Covered: each validation error
with its message, the naming rules, the header's declarations for a
two-function API, the pin blocks present with driver data and absent
without, the cdef's freedom from `#` lines, asserts and the `NS_API`
token, the literal constants and computed masks, and the command line
writing the two destination paths into a temporary directory. `just api-gen-test` runs them in the container.

The end-to-end check is the project's own loop: `just test` generates
from the real definition, builds the library against the generated header
with the pins active, builds the test program, and runs the Lua test
through the generated module in the guest.

## Extension points

- A new output is a new `emit_*.py` taking the `Api`, plus one call in
  `__main__.py` and one path under the output directory that mirrors where
  it will be staged. The header-only C++ wrapper on the roadmap is that
  shape.
- A per-API hooks module beside the definition is reserved for
  peculiarities. Its interface is deliberately undefined until the first
  real case shows what it needs; the model is plain data so a hook can
  adjust it without the generator knowing why.
