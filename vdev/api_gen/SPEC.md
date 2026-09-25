# SPEC – api_gen

The consumer-facing contract of the API generator: what a definition may say, and what every compliant implementation produces from it. How this implementation does so is in ARCHITECTURE.md beside this file. Where the generator sits in the build is in the root ARCHITECTURE.md, "API generation".

## Purpose

A userspace API is stated once, in a definition file, and every artifact a consumer needs is generated from it: a C header that also carries, for the implementation's build only, a compile-time check that the library's constants agree with the driver's UAPI header; a header-only C++ wrapper; a LuaJIT module; and an implementation stub. The definition is the source of truth; the artifacts are build products and are never edited. The definition states meaning, not shape: each output is idiomatic for its own language, and no output copies another's form.

## The definition

One TOML file, `<stem>.adef.toml`. `<stem>` names every output.

Every key that is not a name begins with `_`, at every level: every other key is a member name (a constant, field or parameter), and no member name begins with `_`. `[_general]` and `[_driver_data]` describe no item, so every one of their own keys is a `_`-prefixed property too; `[_driver_data.const_pins]` is a member map, and its keys are names.

- Item properties: `_docstring` (documents the item), `_return` (functions only), `_base_type` (enums and constant groups only), and on an opaque ref `_class`, `_ctor`, `_dtor`.
- Entry attributes: on a constant `_value`, `_docstring`, and for an integer `_format`; on a struct field `_type`, `_docstring`; on a parameter `_type`, `_ref`, `_count`, `_optional`, `_docstring`.
- A naked value is sugar: a constant `name = 4` (or `name = ["a", "b"]`) is exactly `name = { _value = 4 }`, and a field or parameter `name = "u32"` is exactly `name = { _type = "u32" }`. An inline table and a nested `[a.b.c]` table are the same thing; both are accepted everywhere.
- `_ref` states how the callee reaches a parameter: `"in"` is read by the callee, `"out"` is written by it, `"inout"` is both; absent means by value. A `memory` parameter requires `_ref`.
- `_count` is one of the unsigned integer types `"u8"`, `"u16"`, `"u32"`, `"u64"`, required on a `memory` parameter and allowed nowhere else: the type of the buffer's byte count.
- `_optional = true` marks an `in`, `out` or `inout` struct or scalar parameter, or a `memory` parameter with `_ref = "in"`, as one whose null the caller may pass instead of a value; refused on a parameter with no `_ref` (a by-value parameter has no null to pass). A constructor's cached `out` parameter (see the C++ wrapper and the Lua module below) ignores it, since the binding always supplies that parameter itself.
- `_format` is `"hex"` or `"dec"` (the default): how the number is spelled where a literal is emitted.

The file holds these tables, each optional unless stated; any other top-level table is an error:

- `[_general]` (required): `_namespace` (an identifier; the prefix for everything generated), `_version` (four integers 0..255, encoded most-significant first into one 32-bit value; the first byte is 0..127 so the constant fits `int`), `_library` (the shared object file name the script binding loads; a plain file name, no quotes or backslashes). There is no name field: the file stem names every output.
- `[[untyped_bit_const]]`: an array of groups of constants that are bit flags. Each group has an optional `_docstring`, an optional `_base_type`, and at least one entry. An integer value is a bit index, 0..30 so the flag fits `int`. A list sums its terms into the entry's value: each term is an earlier entry of this group or an earlier one, or a literal integer (parsed as TOML itself would: decimal or `0x`-prefixed, an optional leading `-`); the loader refuses a sum whose terms share a bit, naming the two.
- `[[untyped_const]]`: an array of groups of plain integer constants, with the same group properties. A value is an integer fitting a 32-bit signed value, or a list summing the same kind of terms `untyped_bit_const` composes — an earlier entry of this group or an earlier one, or a literal integer — with that range applied to the sum. A floating-point value, or a `_base_type` of `f32` or `f64`, is refused as not implemented.
- `[[string_const]]`: an array of groups of string constants, each with an optional `_docstring` (no `_base_type`: a string has no fixed-width representation) and at least one entry. Values are strings containing no `"`, `\` or newline.
- `[typed_const.<enum>]`: an enumeration, with an optional `_docstring` and `_base_type`. Values are integers fitting a 32-bit signed value.
- `[opaque_ref.<name>]`: a handle type whose representation is the implementation's secret. It has no members, only properties: `_docstring`; and for bindings with object semantics, `_ctor`, the function that produces the handle (it has exactly one parameter of this type with `_ref = "out"`), `_dtor`, the function that releases it (its only parameter is this type by value; requires `_ctor`), and `_class`, the object's name in those bindings, written idiom-free (lowercase identifier; default the ref's name). Each binding applies its own casing.
- `[struct.<name>]`: an optional `_docstring`, then fields in document order.
- `[function.<name>]`: `_return` (a `typed_const` enum name whose entries include the value 0, required), an optional `_docstring`, then parameters in document order. A `memory` parameter `p` becomes, in the C header and every output that mirrors it, an adjacent pair: the pointer `p`, then its byte count `p_count` of the `_count` type. The definition does not write the count; a numeric parameter written beside a buffer is just another parameter.
- `[_driver_data]`: `_header`, the driver's UAPI header path relative to the exercises directory (no quotes or backslashes), and `[_driver_data.const_pins]`, mapping an `untyped_bit_const` key to the driver macro it must equal.

`_base_type` is `"i32"` (the default) or `"u32"`, and chooses the fixed-width type the C++ wrapper and the Lua FFI declarations give an enum or a group's constants. The C header spells every constant as an enumerator whatever the base type, so values still fit `int` under `u32`; `u32` adds that no value is negative.

Rules a definition must satisfy:

- Types are the integer types `i8`, `u8`, `i16`, `u16`, `i32`, `u32`, `i64`, `u64`, the floating-point types `f32`, `f64`, `memory`, or a name from `typed_const`, `opaque_ref` or `struct`. The builtins other than `memory` are variable types only: `_base_type` and `_count` take the values stated for them. Those three categories share one namespace; a name in two of them is an error, as is shadowing a builtin.
- A key beginning with `_` that is not recognised where it appears is an error naming the key and where; so is a key not beginning with `_` inside an entry's table or an opaque ref. `[untyped_const]`, `[untyped_bit_const]` and `[string_const]` written as single tables are an error: each is an array of tables, `[[...]]`. A group has at least one entry.
- A `memory` parameter's `p_count` is not the name of another parameter of the same function.
- Every name is a C identifier that is neither a C, C++ nor Lua keyword; no parameter is named `self`, `result`, `lib`, `M`, `ffi` or `indent`, the locals the generated code binds.
- A composed constant names only entries defined before it, in its own group or an earlier one. A pin names an existing `untyped_bit_const` entry. Constant names are unique across every constant group, the string constants, every enum, and the version constant; the C identifiers of enums, opaque refs and their tags, structs and functions are unique together.
- Docstrings contain neither `*/` nor `]]`.
- Order is meaning: parameters, fields and constant groups appear in every output in the order written.
- A ctor has no `memory` parameter with `_ref = "out"` and no parameter with `_ref = "inout"`: the bindings cache every other `out` of the ctor on the object, a buffer has no owner there, and a constructor has nothing to return an updated value through.

## Naming

With namespace `ns`, upper-cased `NS`:

| definition | generated |
|---|---|
| bit, plain, string constant or enum entry `key` | `NS_KEY` in C; `KEY` in a module-scoped binding |
| `_general._version` | `NS_API_VERSION` |
| enum `e` | `enum ns_e`, typedef `ns_e` |
| opaque ref `h` | `struct ns_h_opaque`, typedef `ns_h` (a pointer) |
| struct `s` | `struct ns_s`, typedef `ns_s` |
| function `f` | `ns_f` |
| `memory` parameter `p` | `p`, then its byte count `p_count` |
| in C++: enum `e`, entry `k`, struct `s`, class `c` | `ns::E`, `E::K`, `ns::S`, `ns::C` (UpperCamel) |
| `_base_type` `i32`, `u32` | `int32_t`, `uint32_t` in the C++ wrapper and the Lua FFI declarations |
| visibility macros | `NS_C_API`, `NS_API`, with `NS_IMPL` as the implementation's define |

## Outputs

Every output starts with a banner naming its source and saying it is generated. Under the output directory:

### `include/<exercise>/<stem>.h` — the C header

- For a consumer, includes only `<stdint.h>`. Its preprocessor content is: `#pragma once`, that include, the two blocks defining `NS_C_API` (`extern "C"` under C++) and `NS_API` (`NS_C_API` plus default visibility when `NS_IMPL` is defined), and the implementation-only blocks below. No macro is used in any declaration except `NS_API` before each function.
- One block at the end of the file under `#if defined(NS_IMPL)`, and so only in the implementation's build: an include of `<assert.h>` and of the driver header named in `_driver_data._header`, then one file-scope `static_assert(NS_KEY == DRIVER_MACRO, "...")` per pin. The library failing to compile is the ABI check; a consumer never sees the driver header. Absent `[_driver_data]`, the block is not emitted.
- Constants are enums: the version in an anonymous enum, each bit constant group in an anonymous enum with single bits as `(1u << n)` and a composed entry's sum as `A | B`, each plain constant group in an anonymous enum with a composed entry's sum as `A + B`, each typed enum with explicit values and a typedef; a sum's literal term is spelled exactly as the definition wrote it. Each string constant group is a run of `static const char NS_KEY[] = "...";`, so the header stays macro-free.
- Each opaque ref is an incomplete struct and a pointer typedef. Each struct has its fields in order with a typedef.
- Functions are declared in document order. Type mapping: an integer type `iN` → `intN_t` and `uN` → `uintN_t`, `f32` → `float`, `f64` → `double`, an enum or struct by its typedef, an opaque ref by value as its typedef; a non-memory type `T` with `_ref = "in"` → `const T*`, with `"out"` or `"inout"` → `T*`; `memory` → `const void*` when `"in"`, `void*` when `"out"` or `"inout"`, followed by `p_count` of its `_count` type.
- Docstrings become `/* */` comments: above an enum (a constant group's included), struct, opaque ref or function, trailing an enum entry or struct field; a parameter's docstring joins its function's comment as `name: text`.
- The header is not a binding input. The Lua module carries its own FFI declarations, rendered from the same definition, so nothing parses the header at run time and the implementation-only blocks may hold whatever the check needs.

### `include/<exercise>/<stem>.hpp` — the header-only C++ wrapper

A C++20 header beside the C header, including it and nothing but the standard library, inside `namespace <ns>`. Constants are `inline constexpr` under their unprefixed names: the version `uint32_t`, each constant group — bit, plain or string — one run under its `_docstring` as a `//` line, typed by its base type except a string group's `const char*`; each enum is an `enum class` over the C values with its base type as the underlying type, UpperCamel entries and a `to_string`; each struct is an alias of the C typedef. Each opaque ref with a `_ctor` is a class named from `_class` in UpperCamel, move-only (move assignment releases the current handle first): `create(...)` takes the `_ctor`'s parameters other than its non-memory `out`s and returns the class by value, with the call's result written through an optional out-pointer; on failure the object is falsy (null handle, value-initialised members), so `if (!dev)` is the check and no optional is involved; every other `_ctor` `out` is a private member read through a const accessor named after its parameter, `dev.info()`; the destructor and `release()` call the `_dtor`; one method per function, other than the `_ctor` and `_dtor`, whose first parameter is the opaque by value, returning the enum and taking a `memory` parameter as the C header does, pointer then count. A non-memory `in` is `const T&` (a struct by its alias), an `out` or `inout` `T&`, each passed to C by address; an `_optional` struct or scalar `in`/`out`/`inout` method parameter is `const T*` or `T*` instead, forwarded as-is, defaulted to `nullptr`; defaults are trailing, so an `_optional` parameter followed by a non-optional one keeps the pointer type but has no default. A constructor's cached `out` parameters ignore `_optional`. An opaque by value is the C handle type; an enum reached through `_ref` is the C typedef. Results are `[[nodiscard]]`. Casts are functional-style, C names unqualified, fixed-width integers spelled as the C header spells them. No exceptions, no allocation.

### `stub/<stem>.cpp` — the implementation stub

A C++ translation unit to copy into `lib/` once when starting an implementation, never staged and never touched by the generator afterwards: the implementation-macro define around the header include, so the ABI pins compile, the standard headers `<cerrno>`, `<cstdint>` and `<cstring>`, and one definition per function in document order whose body voids every parameter and returns the return enum's `err_unsupported` entry, or its first nonzero entry if there is none. A return enum with no nonzero entry is an error. The signatures match the header byte for byte.

### `binding/<stem>.lua` — the LuaJIT module

A module returned from `require`, needing no file at run time:

- Its `ffi.cdef` text holds only what calls need: `typedef int32_t ns_e;` for each enum (`uint32_t` under `_base_type = "u32"`), the opaque and struct declarations, and the functions without `NS_API`. No constants are declared to the FFI.
- Every constant is a Lua literal, `M.KEY`, with the same value the header gives it: the module is the namespace, so the `NS_` prefix is not repeated. A composed entry's sum is computed; strings are string literals; the version is one 32-bit value. A constant group's `_docstring` is a `--` comment line above its literals.
- `M.<enum>_to_str(value)` maps a value to its unprefixed constant name (two entries with one value map to the later name); `M.error_to_str` is the same alias for the one enum every function returns, and is absent when functions return different enums. `value == nil` maps to the enum's zero-valued entry, since a method returns `nil` in its error position exactly when the C call returned that entry; an enum with no zero-valued entry gets no such clause.
- `M.raw.<f>` is the FFI function for each function.
- For each opaque ref with a `_ctor`, a class `M.<Class>`, the `_class` attribute in UpperCamel with no namespace prefix:
  - `new(...)` takes the `_ctor`'s parameters other than its non-memory `out`s, in order; returns `nil, result` on any result other than the enum's zero-valued entry, else an object whose `_handle` is the opaque value with the `_dtor` as its GC finalizer, and which caches every other `out` of the `_ctor` under that parameter's name: a struct as a plain table copy of its fields (`i64` and `u64` fields as cdata, every other builtin and enum field as a number, nested structs copied the same way), an `i64` or `u64` scalar as cdata, any other builtin or enum scalar as a number. The module emits no display helpers; what a consumer prints is the consumer's.
  - One method per function, other than the `_ctor`, whose first parameter is the opaque by value, taking the other parameters except non-memory `out`s, in order. A non-memory `in` or `inout` value is passed as a Lua value, a struct as a table or cdata and a scalar as a number, and copied into cdata the C call points at; for an `_optional` `in` or `inout` parameter this copy happens only when the caller's value is non-nil, and `nil` passes straight through so the FFI turns it into a null pointer. After a successful call the `out` and `inout` non-memory values are returned in order, a struct as the same plain table, an opaque as the raw handle unwrapped, followed by `nil`; a method with none returns `true, nil`; any other result returns `nil, result`.
  - The `_dtor`'s method releases explicitly: it disarms the finalizer if one is attached, calls the function with whatever `_handle` holds, clears `_handle`, and returns like any method. A second release therefore reaches the library as a null handle and returns whatever the library promises for that, so the function's own contract holds through the class. An object never released is released by the GC finalizer.
  - Every other method begins with an `assert` that `_handle` is set. Use after release is a caller bug and fails as an assertion; the `nil, result` return is reserved for what the library reports.
  - `new` and every method, the `_dtor`'s included, then asserts the type of each of its own arguments in order, one `assert` per argument, after the live-handle assert where there is one and before any FFI allocation or call: `type(x) == "number"` for every builtin other than `i64` and `u64`, a typed-enum value, and a `memory` `out` argument's count; `type(x) == "number" or ffi.istype("uint64_t", x) or ffi.istype("int64_t", x)` for `i64` and `u64` by value or `inout`, since a literal like `48ULL` may hold either C type; `type(x) == "string"` for a `memory` `in` or `inout` argument; `type(x) == "table" or ffi.istype("ns_s", x)` for a struct `s` by `in` or `inout`; `ffi.istype("ns_h", x)` for an opaque `h` passed by value — never a bare `type(x) == "cdata"`, which would accept any cdata regardless of its C type. The message is `"<Class>.<method>: <param> must be <expected>"`, e.g. `"Device.dma_to_device: psrc must be a string"`, `"Port.configure: cfg must be a table or xy_stats"`. An `_optional` parameter's condition gains `x == nil or` and its expected text gains " or nil"; `_optional` on a parameter with no `_ref` is refused (`optional needs a pointer parameter`).
  - An opaque ref without a `_ctor` gets no class; its functions are reachable through `M.raw`.
  - A `memory` parameter is a Lua string, the idiomatic byte container; the generated code never exposes a cdata buffer to the consumer. `_ref = "in"`: the argument is the string, passed straight to the call with its length as `p_count`; `_optional` admits `nil`, passed straight through with a `p_count` of 0. `_ref = "out"`: the argument, in the parameter's position, is `p_count`, a number; the method allocates a buffer of that size, passes it and `p_count` to the call, and returns the bytes written as a string in the out-values position, exactly as a scalar `out` is returned. `_ref = "inout"`: the argument is a string; the method copies it into a buffer of the same length, passes that and its length to the call, and returns the bytes written as a string the same way.
- Results, constants, enum values and every builtin other than `i64` and `u64` are plain Lua numbers. `i64` and `u64` values are cdata: they compare with numbers and print with a `ULL` suffix, and `tonumber` would silently truncate above 2^53.

## Invocation

Two modes. Generation: `python3 -m api_gen <definition> --generated <dir> --exercise <name> [--library <file>]`. `--library` overrides `_general._library`; one of them must be present for the Lua module. Exit status 0 on success with one line on stderr naming what was written; 2 on any definition error, with nothing written and each objection on its own line as `api_gen: <definition>: <what is wrong>`. A definition that breaks the format's own rules draws its first objection; one that satisfies them draws every objection every output has, all in the same run, each naming its output first (`header:`, `wrapper:`, `lua:`, `stub:`). A definition the format allows but the generator does not yet produce is refused the same way, the message saying `not implemented`. Every output is always written; staleness is the build's concern.

Dependencies: `python3 -m api_gen gendeps <definition>` prints make text to stdout for exactly one definition (one per exercise is the rule): `GENERATED :=` listing the outputs as `$(GEN)/...` paths with `$(BASE)` for the exercise directory, and one grouped-target rule (`$(GENERATED) &: definition`, GNU make 4.3 or later) making every output by running the generation mode with `--generated $(GEN) --exercise $(BASE)`. The including makefile defines `GEN`, `BASE` and `API_GEN`. The definition is not read; only its name matters, and the output paths come from the same code the generation mode writes to, so a build file never spells them.

## Not generated

The kernel ioctl header. Its shape is a kernel UAPI header's, not a userspace API's, and it is hand-written; the pins are the bridge. The API's implementation is hand-written too: the stub is a starting point handed over once, and the generator never touches `lib/`.
