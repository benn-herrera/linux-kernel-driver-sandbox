local M = dofile(arg[1])
local p = M.Port.new(1)
p = nil
M = nil
collectgarbage("collect")
collectgarbage("collect")
os.exit(0)
