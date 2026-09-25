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
constants agree with the driver's UAPI header, and a LuaJIT module. The definition is the source of truth; the artifacts are build
products and are never edited.

## The definition

One TOML file, `<stem>.adef.toml`. `<stem>` names every output. The file
holds these tables, each optional unless stated:

- `[general]` (required): `namespace` (an identifier; the prefix for
  everything generated), `version` (four integers 0..255, encoded
  most-significant first into one 32-bit value), `library` (the shared
  object file name the script binding loads). There is no name field:
  the file stem names every output.
- `[untyped_bit_const]`: constants that are bit flags. An integer value is
  a bit index. A list of strings names earlier entries whose flags are
  combined into a mask. Either may be wrapped as `{ value = ..., format =
  "hex"|"dec", docstring = "..." }`; `format` chooses how the number is
  spelled where a literal is emitted, decimal by default.
- `[typed_const.<enum>]`: an enumeration. Entries are integers fitting a
  32-bit signed value, optionally wrapped as `{ value = ..., format =
  "hex"|"dec", docstring = "..." }`. A `docstring` key at the table level
  documents the enum.
- `[opaque_ref.<name>]`: a handle type whose representation is the
  implementation's secret. Attributes: `docstring`; and for bindings with
  object semantics, `ctor`, the function that produces the handle (it has
  exactly one `outref` of this type), `dtor`, the function that releases
  it (its only parameter is this type by value; requires `ctor`), and
  `class`, the object's name in those bindings (an identifier; default the
  ref's name in UpperCamel).
- `[struct.<name>]`: fields in document order, each a type string or `{
  type = "...", docstring = "..." }`. A `docstring` key documents the
  struct.
- `[function.<name>]`: `return` (a `typed_const` enum name, required),
  `docstring`, then parameters in document order, each a type string or an
  inline table with `type` and attributes: `outref` (written by the
  callee), `inref` (read by the callee; for `memory`, pointer-to-const),
  `nullsafe` (documentation: the caller may pass null), `docstring`, and
  for `memory` parameters `size`, naming the sibling parameter that holds
  the byte count.
- `[driver_data]`: `header`, the driver's UAPI header path relative to the
  exercises directory, and `[driver_data.const_pins]`, mapping an
  `untyped_bit_const` key to the driver macro it must equal.

Rules a definition must satisfy:

- Types are `u32`, `u64`, `memory`, or a name from `typed_const`,
  `opaque_ref` or `struct`. Those three categories share one namespace; a
  name in two of them is an error, as is shadowing a builtin.
- `docstring` and `return` are reserved: no parameter, field or entry may
  use them as its name. Every name is a C identifier.
- A composed constant names only entries defined before it. A pin names an
  existing `untyped_bit_const` entry. Constant names are unique across the
  bit constants, every enum, and the version constant.
- Docstrings contain neither `*/` nor `]]`.
- Order is meaning: parameters and fields appear in every output in the
  order written.

## Naming

With namespace `ns`, upper-cased `NS`:

| definition | generated |
|---|---|
| bit constant or enum entry `key` | `NS_KEY` |
| `general.version` | `NS_API_VERSION` |
| enum `e` | `enum ns_e`, typedef `ns_e` |
| opaque ref `h` | `struct ns_h_opaque`, typedef `ns_h` (a pointer) |
| struct `s` | `struct ns_s`, typedef `ns_s` |
| function `f` | `ns_f` |
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
  `A | B`, each typed enum with explicit values and a typedef.
- Each opaque ref is an incomplete struct and a pointer typedef. Each
  struct has its fields in order with a typedef.
- Functions are declared in document order. Type mapping: `u32` →
  `uint32_t`, `u64` → `uint64_t`, an enum or struct by its typedef, an
  opaque ref by value as its typedef; `outref` of a non-memory type `T` →
  `T*`; `memory` → `const void*` when `inref`, `void*` when `outref`.
- Docstrings become `/* */` comments: above an enum, struct or function,
  trailing an enum entry or struct field.
- The header is not a binding input. The Lua module carries its own FFI
  declarations, rendered from the same definition, so nothing parses the
  header at run time and the implementation-only blocks may hold whatever
  the check needs.

### `binding/<stem>.lua` — the LuaJIT module

A module returned from `require`, needing no file at run time:

- Its `ffi.cdef` text holds only what calls need: `typedef int32_t ns_e;`
  for each enum, the opaque and struct declarations, and the functions
  without `NS_API`. No constants are declared to the FFI.
- Every constant is a Lua number literal, `M.NS_KEY`, with the same value
  the header gives it. Composed masks are computed. The version is one
  32-bit value.
- `M.<enum>_to_str(value)` maps a value to its constant name for each enum;
  `M.error_to_str` is the same alias for the one enum every function
  returns, and is absent when functions return different enums.
- `M.raw.<f>` is the FFI function for each function.
- For each opaque ref with a `ctor`, a class `M.<Ns><Class>`:
  - `new(...)` takes the `ctor`'s non-`outref` parameters in order;
    returns `nil, result` on any result other than the enum's zero-valued
    entry, else an object whose `_handle` is the opaque value with the
    `dtor` as its GC finalizer, and which caches every other `outref` of
    the `ctor` under that parameter's name: a struct as a plain table copy
    of its fields (`u32` and enum fields as numbers, `u64` as cdata), a
    scalar as a number. The module emits no display helpers; what a
    consumer prints is the consumer's.
  - One method per function, other than the `ctor` and `dtor`, whose
    first parameter is the opaque by value, taking the other non-`outref`
    parameters in order; `outref` values are returned in order after a
    successful call, followed by `nil`; a method with no `outref` returns
    `true, nil`; any other result returns `nil, result`.
  - An opaque ref without a `ctor` gets no class; its functions are
    reachable through `M.raw`.
  - `memory` with `size`: an `inref` buffer is a Lua string in its
    position and its `size` parameter disappears from the argument list,
    the string's length being passed; an `outref` buffer keeps its `size`
    parameter as an argument and is returned as a string of exactly that
    many bytes. Binary-safe: no terminator is added or assumed.
- Results and constants are plain Lua numbers; nothing the module returns
  needs `tonumber`.

## Invocation

Two modes. Generation:
`python3 -m api_gen <definition> --generated <dir> --exercise <name>
[--library <file>]`. `--library` overrides `general.library`; one of them
must be present for the Lua module. Exit status 0 on success with one line
on stderr naming what was written; 2 on any definition error, with the
message `api_gen: <definition>: <what is wrong>`, and nothing written.
Both outputs are always written; staleness is the build's concern.

Dependencies: `python3 -m api_gen gendeps --generated <dir> --exercise
<name> <definition>...` prints make text to stdout: per definition, a
`GENERATED +=` line naming its outputs and one grouped-target rule
(`a b &: definition`, GNU make 4.3 or later) making both outputs from
the definition by running the generation mode. The rule refers to
the make variable `API_GEN` for the directory holding the package. No
definition is read; only the names matter, and the output paths come
from the same code the generation mode writes to, so a build file never
spells them. With no definitions, only the banner is printed.

## Not generated

The kernel ioctl header. Its shape is a kernel UAPI header's, not a
userspace API's, and it is hand-written; the pins are the bridge. The
API's implementation is hand-written too; the generator never touches it.
