# README – api_gen

**ACKNOWLEDGEMENT** - api_gen is AI-generated code.
The .adef.toml file specification was human designed & authored, the generation system was human specified, but this Python
module's code was agentically produced.

## Human design spec provided

### A C header is a rotten single source of truth

A C header is an idiomatic expression of an API. Transforming one idiom to another while also imposing artificial restrictions on the usage of the single source of truth coding language introduces unnecessary complexities and gotchas.

What the generator produces today, seven outputs among them a Rust binding, a Rust ABI relay and a Rust implementation stub, is listed in SPEC.md, "Outputs".

### Additional human inputs

The agent's inputs to this system also included hand-coded versions of a C API header and LuaJIT binding as well as the implementation of that API and a Lua script that consumed the existing binding and ran device tests.

Those human-authored implementations of the C API and Lua testing script are still in use. The generated header and binding simply replaced the originals.

## Editor support

`api_def.schema.json` gives a Taplo-backed editor (Zed among them) completion, hover text and key diagnostics in a definition: in this repository the root `.taplo.toml` maps `exercises/**/*.adef.toml` to it, and a definition elsewhere can carry the Taplo directive `#:schema <path relative to the definition>` on its first line instead.
