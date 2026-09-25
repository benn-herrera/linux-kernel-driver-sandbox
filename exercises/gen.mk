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
# one definition per exercise; the generated rules and the stub/wrapper naming assume it
DEF := $(wildcard *.adef.toml)
ifneq ($(words $(DEF)),1)
$(error api_def/ holds exactly one *.adef.toml (found: $(if $(DEF),$(DEF),none)))
endif
ADEF_MK := $(GEN)/adef.mk

.DEFAULT_GOAL := all
.PHONY: all clean

# Make remakes an out-of-date included makefile and restarts before reading
# the rest of this file, so a new or changed definition regenerates
# $(ADEF_MK) first; `all` below sees the GENERATED variable from
# that fresh pass, not a stale one. The included file refers to GEN, BASE
# and API_GEN, defined above. A plain `include`, not `-include`: make
# ignores a failed remake of a `-include`d file and would carry on with
# nothing to build.
include $(ADEF_MK)

all: $(GENERATED)

# written through a temp file so a failed gendeps leaves no truncated adef.mk
$(ADEF_MK): $(DEF)
	@mkdir -p $(GEN)
	PYTHONPATH=$(API_GEN) PYTHONDONTWRITEBYTECODE=1 python3 -m api_gen gendeps $(DEF) > $@.tmp && mv $@.tmp $@

clean:
	rm -rf $(GEN)
