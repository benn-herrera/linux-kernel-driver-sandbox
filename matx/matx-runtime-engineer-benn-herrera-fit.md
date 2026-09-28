# MatX Runtime Engineer / Benn Herrera Fit

[Benn Herrera](https://bennherrera.me)'s self-assessment of work and project experience applicability to the problem space and requirements for the role of [Runtime Engineer at MatX](https://jobs.ashbyhq.com/matx/83eeb688-261b-4723-8f3f-90475a6e10cf).

Authorship note: This document was hand-authored. AI was used for review, but the content is mine. -bph

## Core Requirements

### Systems programming language: memory management, allocator design, FFI/ABI

#### Overlap
C++ and C are primary languages across decades of career, with manual memory management and performance considerations the tools of the profession. Multiple projects authored and joined involved FFI, ABI, API, and data format design with versioned change strategies from the producer and consumer sides. 

See specifics under sections below:
- API/ABI contracts
- Python interop
- Custom allocator design

#### Delta
- None beyond internal MatX needs not visible from text of the req

#### Questions
- High proficiency systems programming is table stakes for a role like this. The questions are all in the specifics below.

### Python interop layers in production: PyO3, ctypes, pybind11, C-ABI bridging

#### Overlap
On-point experience with ctypes, significant tangential experience in the problem space.

- Python ctypes: Refactored a container-deployed 3D geometry analysis module from pure C exe to .so with C API bound to Python via ctypes
  - Improved reliability, speed, and eliminated crufty Python -> exe -> out file -> Python dogleg.
- Extensive related experience binding native code to other languages. Examples all designed and built from scratch.
  - C++ API <-- Kotlin via JNI, Swift (Kreativ cross-platform mobile engine)
    - High-frequency/low latency touch events bit packed to int64 to bypass JNI->C marshalling
    - High-frequency/low latency engine->Android logging and metrics via named pipe
  - C++ API <-- LuaJIT (personal game engine project, Linux kernel driver sandbox - see Driver-adjacent section below)
  - Many <-> Many pan-platform, pan-language binding generator, [xplatter](https://github.com/benn-herrera/xplatter)

#### Delta
- No PyO3, pybind11

#### Questions
- It seems like the binding approach and tech (Rust -> Python via PyO3, Rust -> C ABI for shim) have been selected and are in use. Primary question about domain familiarity, then?
- Are all of the intended bindings already planned or started? Are there more on the roadmap that are TBD?

### API/ABI contracts between teams: versioning, evolution, breaking-change discipline

#### Overlap
Extensive experience with full cross-team initiation and ownership.

- Kreativ Engine/Renderer
  - Designed and built initial Android version of Kreativ decoration experience from Kotlin UI on down
  - Carved off the app-side code and transferred to the Android UI/UX team with pure Kotlin API over native C++ functionality
    - Versioned API strictly separated app from engine concerns (no 3D awareness, screen space only, no sync concerns)
  - Ported engine to iOS and managed migration of existing prototype UI to use engine
    - Created matching Swift binding layer and API and handed off to iOS UI/UX team
  - Managed API contract with apps across multiple revisions with significant feature rollouts
  - Engine offered additional Python-wrapped HTTP API for dev controls, diagnostics, external driving
    - APIs used for CI integration tests, asset & render quality tooling, ML R&D team for visualization and demos
- Kreativ Room and Composition 3D Formats
  - Identified shortcomings of custom formats, advocated for company-wide conversion to new standards-based format
  - Built and demoed prototype, coordinated final design and versioning scheme with other teams (backend, ML room perception, web client, mobile clients)
  - Designed testing protocol, tracked cross-team work, advocated design contributions from across the organization
  - Breaking change strategy was dual support with full A/B switchability from developer flows all the way to consumer-facing remote feature switches 
  - End to end was about 2 months from conception to full new pipeline being live in "develop" environment with delivery to "prod" a month later
  - New data formats led to significant reduction in bug hunting time (3rd party tools trivially resolved who owned what bug)
  - Also led to accelerated feature development - cloud-rendered beauty shots of user scenes, ML team's full 3D room scan had a 3D format landing pad (speaking of data versioning, that was where our approach proved itself)
- Design and implementation contributor to Leap Motion SDK versioned API. Established single precision floats as user-facing numeric type. This kept the door open to native or plugin integration with 100% of available game engines and performance conscious user applications. Doubles would have shut out the vast majority.
- API/ABI design most recently demonstrated in Linux kernel driver sandbox project API code gen - definition-driven contract with automated detection of drift. (see Driver-adjacent section below)

#### Delta
- None beyond MatX internals not described in the req

#### Questions
- What are the expectations for cross-team ownership of the role? Is it full "this is my responsibility" driving all the things? Is it understanding the needs of someone who is doing that? Both?

### Accelerator programming model: device memory, async execution, kernel launch

#### Overlap
Significant on-point experience via 3D graphics architecture and engineering.

- Wrote two multi-platform mobile/desktop Vulkan 3D renderers with engines from scratch, latest for Kreativ, shipped to millions
- Design included separate engine, rendering threads, renderer synced to Vulkan device execution
- Management of device life cycle, pipelines, device memory, descriptor sets, descriptor binding
- Designed and built system for vertex, fragment, compute shader compilation/linking/binding/execution
- Render engine included support for one-shot compute dispatch (kernel launch) of either compute or graphics shader, exposed to engine via generic API
- Bidirectional memory coordination: CPU->GPU (asset upload), CPU<-GPU (frame capture, utility shader results readback)

#### Delta
- No inference-specific shipped products

#### Questions
- To what extent is tensor accelerator management a subset vs. superset of 3D graphics engineering?

### ML-systems literate: training and inference loop, collectives, tensor layout

#### Overlap
Literate, mostly.

- Training and inference loop: conceptual, some personal project experience.
  - Autoregression and diffusion inference only affect contents of HBM in MatX design (per Reiner Pope's vodcast talks). See LLM inference internals section below
  - Training requires back-propagation which means updating model weights in the accelerator's SRAM buffers (a non-trivial problem given the SRAM upload channel described in those same talks)
- Tensor layout
  - Placement and arrangement of tensors in memory (contiguity, tiling, ordering). Similar problems to large texture layout for graphics.
  - Quantization formats are analogous to texture block compression formats - rapidly decodable rectangular regions of arbitrarily large 2D or 3D memory layouts
  - Tiling in this context sounds likely analogous to Vulkan texture tiling (VK_IMAGE_TILING_LINEAR, VK_IMAGE_TILING_OPTIMAL, etc.) 

#### Delta
- No exposure to collectives. Looked it up, but no owned knowledge.

#### Questions
- To what extent will data center operational patterns be front-of-mind day-to-day for the runtime engineer?
- It sounds like this falls under the heading of not primary job. Important context to ensure downstream pragmatics don't get torpedoed?

## Bonus

### LLM inference internals (vLLM, TensorRT-LLM, SGLang)

#### Overlap
Co-built with AI a custom, data-driven, modular [inference engine in Go](https://github.com/benn-herrera/go-inference-lab-bench)

- Designed and directed the engine architecture - data driven, no model specific code
  - GGML used for GPU acceleration via thin, custom binding layer
  - Multiple families supported in dense & MoE, with vision towers for two, plus one text diffusion model
  - GGUF loading for all supported model families and Safetensors loading for three of them
  - Logprobs-based equivalency testing for chat and vision against llama.cpp reference
  - Serves OpenAI REST API with additional fields for metrics and dev controls
- Used the project as a way to learn about attention, model layers, RoPE, YaRN, residual accumulation, MoE vs dense, autoregression vs diffusion

#### Delta
- Directed and designed, but not hand-authored
- No multi-request serving

#### Questions
- Not many questions on the internal relevance of this topic. Pretty obvious why it would be good operating knowledge. 
- The req is for working on the runtime consumed by inference engines upstream, not for writing them.

### Rust at depth (proc macros, unsafe with soundness reasoning, lifetimes/traits)

#### Overlap
Low but non-zero.

- One toy project, one agent-coded project ([laterm](https://github.com/benn-herrera/laterm))
- Current comprehension
  - Borrow checker is C++ ownership best practices enforced at compile time
  - Unsafe soundness is the re-transfer of part of that burden to developer discipline
  - Proc macros are authored code run at compile time via in-source annotations (similar to Python decorators, but at compile vs run time)

#### Delta
- Never chosen for hands-on work in professional or personal context

#### Questions
- Expected ramp-up time for experienced multi-language engineer?
- Kernel drivers and device APIs are correctness, robustness, security sensitive. Current AI coding practices? Answer determines primary skill as authoring or review.
- Unsafe Rust review practices (CI linting, AI code review, human code review)?

### Custom allocator design (slab, paged, arena) or other low-level memory work

#### Overlap
Extensive, multiple projects and domains.

- Built RAM filesystem for PS4 to mediate between Telltale Games engine I/O pattern and platform behavior
  - Allocated one memory arena at start time, disbursed via fixed-size block allocation for streaming writes of unknown size
  - Read disk storage contents once at startup, streamed writes from cache following writable file close
  - Provided I/O activity hook to engine for TRC-specified save/load icon display
- Multiple engine projects used separate memory arenas with attached usage-pattern allocator mechanisms
  - Fixed-size/lookaside list allocator - rapid alloc/free cycles, known object size, unknown lifespan
  - Linear allocator - rapid, sequential, mixed-size allocs with single collective free - display lists and per-frame data.
  - Mini-heap allocator - last resort for unknown size and lifespan. Arena allocated from system at startup
- CPU backed GPU device memory buffer management, GPU on-device memory management
  - CPU memory backing could also be paged out to storage and demand-loaded for provision to GPU
  - GPU texture memory management via Vulkan API
  - PS4 Onion/Garlic dual memory bus allocation selection and management

#### Delta
- Graphics application and device specific vs inference specific

#### Questions
- How different will SRAM for weights / HBM for KV cache be from previous device memory management?

### ML framework integration (PyTorch custom backends, JAX/XLA, ONNX runtime)

#### Overlap
- Conceptual
  - JAX system uses Python to express tensor operations via script statements in "immediate-mode" terms
  - The result is data that feeds an IR code gen and compilation process to produce a device-ready compiled executable
  - Could be analogized to the Vulkan 'vkCmd*' API for building a re-usable command buffer from immediate-appearing functions
  - Hands-on experience with numpy provides some basis for understanding

#### Delta
- No direct hands-on with these systems

#### Questions
- Will JAX familiarity be primarily used to read and understand the demands being made of the runtime and simulation layers?
- Are there existing test fixtures that use JAX or some "JAXsimile" to exercise existing or planned simulation code?

### Profiler or tracing infrastructure (perfetto, Nsight, custom)

#### Overlap
Parallel rather than direct.

- perfetto/Nsight directly, no. Related tools, yes. 
  - RenderDoc, PIX graphics debuggers using API stream capture with post-run examination and live hardware playback
  - Familiar with Vulkan command queue based performance timers
- Custom
  - Authored metadata-driven HTML interface to 3D engine and renderer dev control surfaces with realtime performance metrics via high throughput web socket. (Kreativ engine)
  - Multiple implementations in professional engine work of performance vs. budget EKG style graphs

#### Delta
- Usage of named tools, inference-specific custom instrumentation

#### Questions
- Are profiling tools used in a CI context to detect PRs that would regress performance?

### Driver-adjacent or kernel-bypass work, or new-silicon bring-up

#### Overlap
Mixed.

- Driver-adjacent: solid
  - Recent [Linux driver sandbox](https://github.com/benn-herrera/linux-kernel-driver-sandbox) project implementing full stack from kernel driver to test in bound scripting language
  - Wrote OpenCL loader for Android native, experience with MoltenVK and lavapipe ICDs
  - Built multiple Vulkan 1.1 (lowest common denominator on mobile) renderers in professional (Kreativ, shipped to millions) and personal (game engine) projects
- Kernel-bypass work: conceptual familiarity
  - Concept: multi-process mediation of shared device resources in kernel driver (sandbox project)
  - Concept: Expose parts of device engineered to handle multiple users in silicon, driver-manage the parts that are not
- New silicon: tangential
  - Development on new game consoles with beta-quality tool chains and dev tooling.
  - Finding the edges of what works and working around what doesn't while coloring inside the first party tech req lines.
  - Implemented standard crash detection and hot restart of fixed function pipeline GPU (Wii) to work around bug in silicon.

#### Delta
- No hands-on with kernel bypass implementation
- No experience with novel silicon being developed in-house

#### Questions
- Sounds like domain familiarity for cross-discipline collaboration and comprehension of other teams' needs. True/False?
- General understanding of hardware design and manufacturing sufficient to ramp quickly? Where in the process is MatX and what are the current points of coordination? Dependencies/constraints?
