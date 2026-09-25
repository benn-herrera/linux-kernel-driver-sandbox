# generic Makefile for an exercise's api_def/
# usage: `include ../../../gen.mk`
# <exercise> is the name of the directory two levels above this Makefile's
# directory: exercises/<exercise>/userspace/api_def/Makefile.
ifeq ($(strip $(OUT)),)
$(error OUT is not set: make OUT=<out_dir> API_GEN=<api_gen_dir>)
endif
ifeq ($(strip $(API_GEN)),)
$(error API_GEN is not set: make OUT=<out_dir> API_GEN=<api_gen_dir>)
endif

# api_def/ -> userspace/ -> <exercise>/
BASE := $(notdir $(abspath $(CURDIR)/../..))

GEN := $(OUT)/generated
DEFS := $(wildcard *.adef.toml)
ADEF_MK := $(GEN)/adef.mk

.DEFAULT_GOAL := all
.PHONY: all clean

# Make remakes an out-of-date included makefile and restarts before reading
# the rest of this file, so a new or changed *.adef.toml regenerates
# $(ADEF_MK) first; `all` below sees the GENERATED variable from
# that fresh pass, not a stale one.
-include $(ADEF_MK)

all: $(GENERATED)

$(ADEF_MK): $(DEFS)
	@mkdir -p $(GEN)
	PYTHONPATH=$(API_GEN) PYTHONDONTWRITEBYTECODE=1 python3 -m api_gen gendeps --generated $(GEN) --exercise $(BASE) $(DEFS) > $@

clean:
	rm -rf $(GEN)
