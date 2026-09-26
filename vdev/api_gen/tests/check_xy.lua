-- Runs support.KITCHEN_SINK's Lua module (arg[1]) against fake_xy.cpp's libxy.so.
-- Prints NAME=value for every constant; every check is an assert, so a failure exits
-- nonzero naming its line.
local M = dofile(arg[1])
local ffi = require("ffi")

-- Calls `fn(...)`, expecting it to fail as an assertion naming `needle`.
local function type_error(needle, fn, ...)
    local ok, err = pcall(fn, ...)
    return ok == false and err ~= nil and err:find(needle, 1, true) ~= nil
end

local function checks()
    for k, v in pairs(M) do
        if type(v) == "number" then
            print(k .. "=" .. string.format("%d", v))
        elseif type(v) == "string" then
            print(k .. "=" .. v)
        end
    end

    assert(M.status_to_string(9) == "ERR_AGAIN")
    assert(M.status_to_string(12345) == "UNKNOWN_STATUS")
    assert(M.mode_to_string(1) == "SLOW")
    assert(M.access_to_string(3) == "ACC_A|ACC_B")
    assert(M.access_to_string(1) == "ACC_A")
    assert(M.access_to_string(0) == "NONE")
    assert(M.access_to_string(9) == "ACC_A|0x8")
    assert(M.access_to_string(-1) == "ACC_A|ACC_B|0xfffffffc")
    assert(M.limit_to_string(16) == "MAX_UNITS")
    assert(M.limit_to_string(M.NEG) == "NEG")
    assert(M.limit_to_string(M.FLOOR) == "FLOOR")
    assert(M.limit_to_string(99) == "UNKNOWN")
    for _, convert in ipairs({M.status_to_string, M.mode_to_string, M.access_to_string, M.limit_to_string}) do
        assert(convert(nil) == "nil")
    end
    assert(M.Token == nil)
    -- FFI functions are cdata, not Lua functions: call them
    assert(M.raw.spend(nil) == M.OK)
    assert(M.raw.reset() == M.OK)

    local none, err = M.Port.new(99)
    assert(none == nil and err == M.ERR_BUSY)

    local p = assert(M.Port.new(3))
    assert(p.pstats.count == 3)
    assert(type(p.pstats.count) == "number")
    assert(p.pstats.bytes == 1099511627776ULL)
    assert(type(p.pstats.bytes) == "cdata")
    assert(p.generation == 7)
    assert(p.pwrap.inner.count == 3)
    assert(p.pwrap.n == 11)

    assert(p:send("abcd") == true)
    assert(M.status_to_string(select(2, p:send("abcd"))) == "nil")
    assert(select(2, p:send("abc")) == M.ERR_BUSY)
    assert(p:recv(5) == "rr\0rr")
    local no_token = ffi.new("xy_token")
    assert(p:configure({count = 5, bytes = 0}, 6, M.SLOW, no_token) == true)
    assert(p:configure(ffi.new("xy_stats", {count = 5}), 6, M.SLOW, no_token) == true)
    -- A bare struct cdata (fields unset) passes the type check; only its count matters to the library.
    assert(pcall(p.configure, p, ffi.new("xy_stats"), 6, M.SLOW, no_token))

    assert(type_error("must be a string", p.send, p, 42))
    assert(type_error("must be a number", p.recv, p, "5"))
    assert(type_error("must be a number", M.Port.new, "1"))
    assert(type_error("must be a table or xy_stats", p.configure, p, "x", 6, M.SLOW, no_token))
    assert(type_error("must be a table or xy_stats", p.configure, p, ffi.new("uint32_t[1]"), 6, M.SLOW, no_token))
    assert(type_error("must be a xy_token", p.configure, p, {count = 5, bytes = 0}, 6, M.SLOW, 42))
    assert(type_error("must be a string", p.send, p, nil))

    assert(select("#", p:stats_of()) == 4)
    local out, count, link, rest = p:stats_of()
    assert(out.count == 42)
    assert(count == 43)
    assert(link ~= nil)
    assert(rest == nil)

    assert(select("#", p:bump(4, {count = 5, bytes = 0}, "abc")) == 4)
    local level, tally, data, bump_rest = p:bump(4, {count = 5, bytes = 0}, "abc")
    assert(level == 5)
    assert(tally.count == 10)
    assert(type(tally.bytes) == "cdata")
    assert(data == "bcd")
    assert(bump_rest == nil)

    assert(p:seek(1099511627776ULL) == true)
    assert(p:seek(ffi.new("int64_t", 1099511627776)) == true)
    assert(p:seek(2 ^ 40) == true)
    assert(select(2, p:seek(48ULL)) == M.ERR_BUSY)
    assert(type_error("must be a number or 64-bit cdata", p.seek, p, ffi.new("xy_stats")))

    local next_big, next_delta, tune_rest = p:tune(-3, -1099511627776LL, 200, 0.5)
    assert(next_big == -1099511627777LL)
    assert(type(next_big) == "cdata")
    assert(next_delta == -4)
    assert(type(next_delta) == "number")
    assert(tune_rest == nil)
    assert(p:tune(-3, -2 ^ 40, 200, 0.5))
    assert(select(2, p:tune(-3, -2 ^ 40, 199, 0.5)) == M.ERR_BUSY)
    assert(select(2, p:tune(-3, -2 ^ 40, 200, 0.25)) == M.ERR_BUSY)
    assert(type_error("must be a number", p.tune, p, -3, -2 ^ 40, "200", 0.5))
    assert(type_error("scale must be a number", p.tune, p, -3, -2 ^ 40, 200, "0.5"))
    assert(type_error("must be a number or 64-bit cdata", p.tune, p, -3, "big", 200, 0.5))

    assert(p:annotate(nil) == true)
    assert(p:annotate({count = 7, bytes = 0}) == true)
    assert(select(2, p:annotate({count = 1, bytes = 0})) == M.ERR_BUSY)
    assert(type_error("must be a table or xy_stats or nil", p.annotate, p, 42))

    -- _optional memory in, scalar in and scalar inout: nil passes through as a null pointer
    assert(select("#", p:probe(nil, nil, nil)) == 4)
    local mode, no_level, peek, probe_rest = p:probe(nil, nil, nil)
    assert(mode == M.SLOW and no_level == nil and peek == 9 and probe_rest == nil)
    assert(select(2, p:probe("ab", 3, 4)) == 5)
    assert(select(2, p:probe("abc")) == M.ERR_BUSY)
    assert(select(2, p:probe(nil, 4)) == M.ERR_BUSY)
    assert(type_error("payload must be a string or nil", p.probe, p, 42))
    assert(type_error("limit must be a number or nil", p.probe, p, nil, "3"))

    -- a boxed scalar: the caller passes and receives its base type's value, never the box
    assert(select("#", p:echo_offset(2 ^ 40)) == 2)
    local moved_to = p:echo_offset(2 ^ 40)
    assert(moved_to == 1099511627776ULL)
    assert(type(moved_to) == "cdata")
    assert(p:echo_offset(48ULL) == 48ULL)
    assert(type_error("pos must be a number or 64-bit cdata", p.echo_offset, p, "48"))

    assert(p:destroy_port() == true)
    local again, again_err = p:destroy_port()
    assert(again == nil and again_err == M.ERR_OTHER)
    assert(pcall(p.send, p, "abcd") == false)

    local data_link = assert(M.DataLink.new())
    assert(data_link._handle ~= nil)

    for i = 1, 4 do
        assert(M.Port.new(i))
    end
    collectgarbage("collect")
    collectgarbage("collect")
    assert(M.Port.new(1))
end

-- A failure leaves Ports with GC finalizers behind; luajit's error exit collects them
-- after unloading the library and crashes before printing the error, so report it here
-- and exit without closing the state.
local ok, message = xpcall(checks, debug.traceback)
if not ok then
    io.stderr:write(message, "\n")
    os.exit(1)
end
