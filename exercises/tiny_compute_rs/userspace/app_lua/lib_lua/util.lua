-- shared helpers for the Lua test program: ships beside it under /usr/bin/lib_lua/,
-- reached as require("lib_lua.util") through the guest's LUA_PATH from any cwd
local tcdl = require("binding.tcdl_api")

local M = {}

function M.printf(f, ...)
    print(string.format(f, ...))
end

function M.dev_info_to_string(info, indent)
    indent = indent or ""
    return table.concat({
        indent .. "api_version: " .. tostring(info.api_version),
        indent .. "device_idx: " .. tostring(info.device_idx),
        indent .. "dma_buf_size: " .. tostring(info.dma_buf_size),
        indent .. "dma_alignment: " .. tostring(info.dma_alignment),
        indent .. "device_caps: " .. tcdl.cap_to_string(info.device_caps),
    }, "\n")
end

return M
