# SPEC – api_gen

The consumer-facing contract of the API generator: what a definition may
say, and what every compliant implementation produces from it. How this
implementation does so is in ARCHITECTURE.md beside this file. Where the
generator sits in the build is in the root ARCHITECTURE.md, "API
generation".

## Purpose

A userspace API is stated once, in a definition file, and every artifact a
consumer needs is generated from it: a C header that also carries, for
the implementation's build only, a compile-time check that the library's
constants agree with the driver's UAPI header; a header-only C++
wrapper; a LuaJIT module; and an implementation stub. The definition is
the source of truth; the artifacts are build products and are never
edited. The definition states meaning, not shape: each output is
idiomatic for its own language, and no output copies another's form.

## The definition

One TOML file, `<stem>.adef.toml`. `<stem>` names every output. The file
holds these tables, each optional unless stated:

- `[general]` (required): `namespace` (an identifier; the prefix for
  everything generated), `version` (four integers 0..255, encoded
  most-significant first into one 32-bit value; the first byte is 0..127
  so the constant fits `int`), `library` (the shared object file name the
  script binding loads; a plain file name, no quotes or backslashes).
  There is no name field: the file stem names every output.
- `[untyped_bit_const]`: constants that are bit flags. An integer value is
  a bit index, 0..30 so the flag fits `int`. A list of strings names
  earlier entries whose flags are
  combined into a mask. Either may be wrapped as `{ value = ..., format =
  "hex"|"dec", docstring = "..." }`; `format` chooses how the number is
  spelled where a literal is emitted, decimal by default.
- `[untyped_const]`: plain integer constants, no composition. Entries are
  integers fitting a 32-bit signed value, optionally wrapped as `{ value
  = ..., format = "hex"|"dec", docstring = "..." }`.
- `[string_const]`: string constants. Entries are strings, optionally
  wrapped as `{ value = "...", docstring = "..." }`; a value contains no
  `"`, `\` or newline.
- `[typed_const.<enum>]`: an enumeration. Entries are integers fitting a
  32-bit signed value, optionally wrapped as `{ value = ..., format =
  "hex"|"dec", docstring = "..." }`. A `docstring` key at the table level
  documents the enum.
- `[opaque_ref.<name>]`: a handle type whose representation is the
  implementation's secret. Attributes: `docstring`; and for bindings with
  object semantics, `ctor`, the function that produces the handle (it has
  exactly one `outref` of this type), `dtor`, the function that releases
  it (its only parameter is this type by value; requires `ctor`), and
  `class`, the object's name in those bindings, written idiom-free
  (lowercase identifier; default the ref's name). Each binding applies
  its own casing.
- `[struct.<name>]`: fields in document order, each a type string or `{
  type = "...", docstring = "..." }`. A `docstring` key documents the
  struct.
- `[function.<name>]`: `return` (a `typed_const` enum name whose entries
  include the value 0, required),
  `docstring`, then parameters in document order, each a type string or an
  inline table with `type` and attributes: `outref` (written by the
  callee), `inref` (read by the callee; for `memory`, pointer-to-const),
  `nullsafe` (documentation: the caller may pass null), `docstring`, and
  for `memory` parameters `size`, naming the sibling parameter that holds
  the byte count.
- `[driver_data]`: `header`, the driver's UAPI header path relative to the
  exercises directory (no quotes or backslashes), and
  `[driver_data.const_pins]`, mapping an
  `untyped_bit_const` key to the driver macro it must equal.

Rules a definition must satisfy:

- Types are `u32`, `u64`, `memory`, or a name from `typed_const`,
  `opaque_ref` or `struct`. Those three categories share one namespace; a
  name in two of them is an error, as is shadowing a builtin.
- `docstring` and `return` are reserved: no parameter, field or entry may
  use them as its name. Every name is a C identifier that is neither a C,
  C++ nor Lua keyword; no parameter is named `self`, `result`, `lib`, `M`,
  `ffi` or `indent`, the locals the generated code binds.
- A composed constant names only entries defined before it. A pin names an
  existing `untyped_bit_const` entry. Constant names are unique across the
  bit constants, the plain and string constants, every enum, and the
  version constant; the C identifiers of enums, opaque refs and their
  tags, structs and functions are unique together.
- Docstrings contain neither `*/` nor `]]`.
- Order is meaning: parameters and fields appear in every output in the
  order written.

## Naming

With namespace `ns`, upper-cased `NS`:

| definition | generated |
|---|---|
| bit, plain, string constant or enum entry `key` | `NS_KEY` in C; `KEY` in a module-scoped binding |
| `general.version` | `NS_API_VERSION` |
| enum `e` | `enum ns_e`, typedef `ns_e` |
| opaque ref `h` | `struct ns_h_opaque`, typedef `ns_h` (a pointer) |
| struct `s` | `struct ns_s`, typedef `ns_s` |
| function `f` | `ns_f` |
| in C++: enum `e`, entry `k`, struct `s`, class `c` | `ns::E`, `E::K`, `ns::S`, `ns::C` (UpperCamel) |
| visibility macros | `NS_C_API`, `NS_API`, with `NS_IMPL` as the implementation's define |

## Outputs

Every output starts with a banner naming its source and saying it is
generated. Under the output directory:

### `include/<exercise>/<stem>.h` — the C header

- For a consumer, includes only `<stdint.h>`. Its preprocessor content is:
  `#pragma once`, that include, the two blocks defining `NS_C_API`
  (`extern "C"` under C++) and `NS_API` (`NS_C_API` plus default
  visibility when `NS_IMPL` is defined), and the implementation-only
  blocks below. No macro is used in any declaration except `NS_API`
  before each function.
- One block at the end of the file under `#if defined(NS_IMPL)`, and so
  only in the implementation's build: an include of `<assert.h>` and of
  the driver header named in `driver_data.header`, then one file-scope
  `static_assert(NS_KEY == DRIVER_MACRO, "...")` per pin. The library
  failing to compile is the ABI check; a consumer never sees the driver
  header. Absent `[driver_data]`, the block is not emitted.
- Constants are enums: the version in an anonymous enum, the bit constants
  in an anonymous enum with single bits as `(1u << n)` and masks as
  `A | B`, the plain constants in an anonymous enum, each typed enum with
  explicit values and a typedef. String constants are `static const char
  NS_KEY[] = "...";`, so the header stays macro-free.
- Each opaque ref is an incomplete struct and a pointer typedef. Each
  struct has its fields in order with a typedef.
- Functions are declared in document order. Type mapping: `u32` →
  `uint32_t`, `u64` → `uint64_t`, an enum or struct by its typedef, an
  opaque ref by value as its typedef; `inref` of a non-memory type `T` →
  `const T*`; `outref` of a non-memory type `T` → `T*`; `memory` →
  `const void*` when `inref`, `void*` when `outref`.
- Docstrings become `/* */` comments: above an enum, struct, opaque ref
  or function, trailing an enum entry or struct field; a parameter's
  docstring joins its function's comment as `name: text`.
- The header is not a binding input. The Lua module carries its own FFI
  declarations, rendered from the same definition, so nothing parses the
  header at run time and the implementation-only blocks may hold whatever
  the check needs.

### `include/<exercise>/<stem>.hpp` — the header-only C++ wrapper

A C++20 header beside the C header, including it and nothing but the
standard library, inside `namespace <ns>`. Constants are `inline
constexpr` under their unprefixed names; each enum is an `enum class`
over the C values with UpperCamel entries and a `to_string`; each struct
is an alias of the C typedef. Each opaque ref with a `ctor` is a class
named from `class` in UpperCamel, move-only (move assignment releases
the current handle first): `create(...)` takes the `ctor`'s
non-`outref` parameters and returns the class by value, with the call's
result written through an optional out-pointer; on failure the object
is falsy (null handle, value-initialised members), so `if (!dev)` is the
check and no optional is involved; every other `ctor` outref is a
private member read through a const accessor named after its parameter,
`dev.info()`; the destructor and `release()` call the `dtor`; one
method per function,
other than the `ctor` and `dtor`, whose first parameter is the opaque
by value, returning the enum and taking `memory` parameters as the C
header does, pointer and count in the definition's order. Results are
`[[nodiscard]]`. An opaque by value is the C handle type; an enum
`inref` or `outref` is the C typedef. Casts are functional-style, C names
unqualified, fixed-width integers spelled as the C header spells them.
No exceptions, no allocation.

### `stub/<stem>.cpp` — the implementation stub

A C++ translation unit to copy into `lib/` once when starting an
implementation, never staged and never touched by the generator
afterwards: the implementation-macro define around the header include,
so the ABI pins compile, the standard headers `<cerrno>`, `<cstdint>` and
`<cstring>`, and one definition per function in document order whose
body voids every parameter and returns the return enum's
`err_unsupported` entry, or its first nonzero entry if there is none. A
return enum with no nonzero entry is an error. The signatures match the
header byte for byte.

### `binding/<stem>.lua` — the LuaJIT module

A module returned from `require`, needing no file at run time:

- Its `ffi.cdef` text holds only what calls need: `typedef int32_t ns_e;`
  for each enum, the opaque and struct declarations, and the functions
  without `NS_API`. No constants are declared to the FFI.
- Every constant is a Lua literal, `M.KEY`, with the same value the
  header gives it: the module is the namespace, so the `NS_` prefix is
  not repeated. Composed masks are computed; strings are string literals;
  the version is one 32-bit value.
- `M.<enum>_to_str(value)` maps a value to its unprefixed constant name
  (two entries with one value map to the later name);
  `M.error_to_str` is the same alias for the one enum every function
  returns, and is absent when functions return different enums.
- `M.raw.<f>` is the FFI function for each function.
- For each opaque ref with a `ctor`, a class `M.<Class>`, the `class`
  attribute in UpperCamel with no namespace prefix:
  - `new(...)` takes the `ctor`'s non-`outref` parameters in order;
    returns `nil, result` on any result other than the enum's zero-valued
    entry, else an object whose `_handle` is the opaque value with the
    `dtor` as its GC finalizer, and which caches every other `outref` of
    the `ctor` under that parameter's name: a struct as a plain table copy
    of its fields (`u32` and enum fields as numbers, `u64` as cdata,
    nested structs copied the same way), a `u32` or enum scalar as a
    number, a `u64` as cdata. The module emits no display helpers; what a
    consumer prints is the consumer's.
  - One method per function, other than the `ctor`, whose first
    parameter is the opaque by value, taking the other non-`outref`
    parameters in order; an `inref` struct is passed as a table or cdata,
    an `inref` scalar as a number. `outref` values are returned in order
    after a successful call, a struct as the same plain table, an opaque
    as the raw handle unwrapped, followed by `nil`; a method with no `outref` returns `true, nil`; any other
    result returns `nil, result`.
  - The `dtor`'s method releases explicitly: it disarms the finalizer if
    one is attached, calls the function with whatever `_handle` holds,
    clears `_handle`, and returns like any method. A second release
    therefore reaches the library as a null handle and returns whatever
    the library promises for that, so the function's own contract holds
    through the class. An object never released is released by the GC
    finalizer.
  - Every other method begins with an `assert` that `_handle` is set.
    Use after release is a caller bug and fails as an assertion; the
    `nil, result` return is reserved for what the library reports.
  - An opaque ref without a `ctor` gets no class; its functions are
    reachable through `M.raw`.
  - `memory` with `size`: an `inref` buffer is a Lua string in its
    position and its `size` parameter disappears from the argument list,
    the string's length being passed; an `outref` buffer keeps its `size`
    parameter as an argument and is returned as a string of exactly that
    many bytes. Binary-safe: no terminator is added or assumed.
- Results, constants, `u32` and enum values are plain Lua numbers. `u64`
  values are cdata: they compare with numbers and print with a `ULL`
  suffix, and `tonumber` would silently truncate above 2^53.

## Invocation

Two modes. Generation:
`python3 -m api_gen <definition> --generated <dir> --exercise <name>
[--library <file>]`. `--library` overrides `general.library`; one of them
must be present for the Lua module. Exit status 0 on success with one line
on stderr naming what was written; 2 on any definition error, with the
message `api_gen: <definition>: <what is wrong>`, and nothing written.
Every output is always written; staleness is the build's concern.

Dependencies: `python3 -m api_gen gendeps --generated <dir> --exercise
<name> <definition>...` prints make text to stdout: per definition, a
`GENERATED +=` line naming its outputs and one grouped-target rule
(`a b c &: definition`, GNU make 4.3 or later) making every output from
the definition by running the generation mode. The rule refers to
the make variable `API_GEN` for the directory holding the package. No
definition is read; only the names matter, and the output paths come
from the same code the generation mode writes to, so a build file never
spells them. With no definitions, only the banner is printed.

## Not generated

The kernel ioctl header. Its shape is a kernel UAPI header's, not a
userspace API's, and it is hand-written; the pins are the bridge. The
API's implementation is hand-written too: the stub is a starting point
handed over once, and the generator never touches `lib/`.
