# README – api_gen

**ACKNOWLEDGEMENT** - api_gen is AI-generated code.
The .apdef.toml file specification was human designed & authored, the generation system was human specified, but this Python
module's code was agentically produced.

## Human design spec provided

### A C header is a rotten single source of truth

A C header is an idiomatic expression of an API. Transforming one idiom to another while also imposing artificial restrictions on the usage of the single source of truth coding language introduces unnecessary complexities and gotchas.

The way out from this is to have a DSL for specifying the API and a generator program to produce:

- C++ friendly pure C header under which an implementation will be written.
- Language bindings - as many as you feel like implementing a generator for
  - lua (LuaJIT FFI)
  - **NYI** header-only C++ api
  - **NYI** Python via ctypes 
- an optional stub file for the C++ implementation

### Additional human inputs

The agent's inputs to this system also included hand-coded versions of a C API header and LuaJIT binding as well as the implementation of that API and a Lua script that consumed the existing binding and ran device tests.

Those human-authored implementations of the C API and Lua testing script are still in use. The generated header and binding simply replaced the originals.
