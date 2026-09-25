-- Runs support.KITCHEN_SINK's Lua module (arg[1]) against fake_xy.cpp's libxy.so.
-- Prints NAME=value for every constant; every check is an assert, so a failure exits
-- nonzero naming its line.
local M = dofile(arg[1])
local ffi = require("ffi")

local function checks()
    for k, v in pairs(M) do
        if type(v) == "number" then
            print(k .. "=" .. string.format("%d", v))
        elseif type(v) == "string" then
            print(k .. "=" .. v)
        end
    end

    assert(M.status_to_str(9) == "ERR_AGAIN")
    assert(M.error_to_str == M.status_to_str)
    assert(M.mode_to_str(1) == "SLOW")
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
    assert(select(2, p:send("abc")) == M.ERR_BUSY)
    assert(p:recv(5) == "rr\0rr")
    assert(#p:recv(5) == 5)
    assert(p:configure({count = 5, bytes = 0}, 6, M.SLOW, nil) == true)
    assert(p:configure(ffi.new("xy_stats", {count = 5}), 6, M.SLOW, nil) == true)

    assert(select("#", p:stats_of()) == 4)
    local out, count, link, rest = p:stats_of()
    assert(out.count == 42)
    assert(count == 43)
    assert(link ~= nil)
    assert(rest == nil)

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
