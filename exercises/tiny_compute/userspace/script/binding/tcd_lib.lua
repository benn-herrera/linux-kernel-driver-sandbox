
--
-- API Binding Init
--
local ffi = require("ffi")
local fhdr, err = io.open("/usr/include/tiny_compute/tcdl_api.h")
if not fhdr then
    error("failed opening tcdl api header file: " .. tostring(err))
end
local api_text = fhdr:read("*a")
fhdr:close()
fhdr = nil

-- strip preprocessor lines and the TCDL_API annotation
api_text = api_text:gsub("#[^\n]*\n", ""):gsub("%f[%w_]TCDL_API%f[^%w_]", "")
ffi.cdef(api_text)
-- print(api_text)
api_text = nil

local lib_tcd = ffi.load("libtiny_compute.so")

-- the module
local M = {
  TCDL_OK = tonumber(ffi.C.TCDL_OK),
  TCDL_ERR_NO_DEVICE = tonumber(ffi.C.TCDL_ERR_NO_DEVICE),
  TCDL_ERR_INVALID_HANDLE = tonumber(ffi.C.TCDL_ERR_INVALID_HANDLE),
  TCDL_ERR_INVALID_ADDRESS = tonumber(ffi.C.TCDL_ERR_INVALID_ADDRESS),
  TCDL_ERR_TIMEDOUT = tonumber(ffi.C.TCDL_ERR_TIMEDOUT),
  TCDL_ERR_DEVICE_DEAD = tonumber(ffi.C.TCDL_ERR_DEVICE_DEAD),
  TCDL_ERR_COMM_FAILED = tonumber(ffi.C.TCDL_ERR_COMM_FAILED),
  TCDL_ERR_UNKNOWN = tonumber(ffi.C.TCDL_ERR_UNKNOWN),
}
local error_strings = {}
for k, v in pairs(M) do
    error_strings[v] = k
end

M.TCDL_API_VERSION = tonumber(ffi.C.TCDL_API_VERSION)
M.TcdlDevice = {}
M.TcdlDevice.__index = M.TcdlDevice

local caps = {
  TCDL_CAP_COMPUTE = tonumber(ffi.C.TCDL_CAP_COMPUTE),
  TCDL_CAP_DMA_READ = tonumber(ffi.C.TCDL_CAP_DMA_READ),
  TCDL_CAP_DMA_WRITE = tonumber(ffi.C.TCDL_CAP_DMA_WRITE),
  TCDL_CAP_DMA_READ_WRITE = tonumber(ffi.C.TCDL_CAP_DMA_READ_WRITE),
  TCDL_CAP_ALL = tonumber(ffi.C.TCDL_CAP_ALL),
}
local cap_strings = {}
for k, v in pairs(caps) do
    -- map value to name
    cap_strings[v] = k
    -- put definition into module
    M[k] = v
end
caps = nil

function M.error_to_str(ecode)
  return error_strings[ecode]
end

function M.TcdlDevice.new(device_idx)
    if device_idx == nil then
        device_idx = 0
    end
    assert(type(device_idx) == "number")
    local pinfo = ffi.new("tcdl_info")
    local phandle = ffi.new("tcdl_handle[1]")
    local result = lib_tcd.tcdl_create_device(device_idx, phandle, pinfo)
    if result ~= M.TCDL_OK then
        return nil, tonumber(result)
    end
    self = setmetatable({}, M.TcdlDevice)
    self.info = {
        api_version = tonumber(pinfo.api_version),
        device_idx = tonumber(pinfo.device_idx),
        dma_buf_size = pinfo.dma_buf_size,
        dma_alignment = tonumber(pinfo.dma_alignment),
        device_caps = pinfo.device_caps,
    }
    local handle = phandle[0]
    self._handle = ffi.gc(handle, lib_tcd.tcdl_destroy_device)
    return self, nil
end

function M.TcdlDevice.get_info_string(self, indent)
    indent = indent ~= nil and indent or ""
    local caps_str = cap_strings[self.info.device_caps]
    if not caps_str then
      caps_str = string.format("0x%08x", self.info.device_caps)
    end
    return string.format(
        indent .. "api_verstion: 0x%08x\n" ..
        indent .. "device_idx: %s\n"..
        indent .. "dma_buf_size: %s\n"..
        indent .. "dma_alignment: %s\n"..
        indent .. "device_caps: %s",
          self.info.api_version,
          self.info.device_idx,
          self.info.dma_buf_size,
          self.info.dma_alignment,
          caps_str)
end

function M.TcdlDevice.check_alive(self)
    local result = lib_tcd.tcdl_check_alive(self._handle)
    if result ~= M.TCDL_OK then
        return false, tonumber(result)
    end
    return true, nil
end

function M.TcdlDevice.compute_factorial(self, arg)
    assert(type(arg) == "number")
    local pfact = ffi.new("uint32_t[1]")
    local result = lib_tcd.tcdl_compute_factorial(self._handle, arg, pfact)
    if result ~= M.TCDL_OK then
        return nil, tonumber(result)
    end
    return tonumber(pfact[0]), nil
end

function M.TcdlDevice.dma_from_device(self, device_offset, count)
    assert(type(device_offset) == "number")
    assert(type(count) == "number")
    local buffer = ffi.new("char[?]", count)
    local result = lib_tcd.tcdl_dma_from_device(self._handle, buffer, device_offset, count)
    if result ~= M.TCDL_OK then
        return nil, tonumber(result)
    end
    return ffi.string(buffer), nil
end

function M.TcdlDevice.dma_to_device(self, text, device_offset)
    assert(type(text) == "string")
    assert(type(device_offset) == "number")
    local buffer = ffi.new("char[?]", #text + 1, text)
    local result = lib_tcd.tcdl_dma_to_device(self._handle, buffer, device_offset, ffi.sizeof(buffer))
    if result ~= M.TCDL_OK then
        return nil, tonumber(result)
    end
    return true, nil
end

return M
