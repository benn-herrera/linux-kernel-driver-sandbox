# generic Makefile for every userspace C/C++ project
# usage: set LINK_TYPE to EXE or SO, then `include ../../../cpp.mk`
#   EXE: builds $(OUT)/<exercise> and links lib<exercise>.so by name
#   SO:  builds $(OUT)/lib<exercise>.so with a matching SONAME
# <exercise> is the name of the directory two levels above this Makefile's
# directory: exercises/<exercise>/userspace/{app,lib}/Makefile.
# Each object also gets a compile_commands fragment, $(OUT)/<lib|app>/<obj>.o.json.
# Generated headers are found at $(OUT)/generated/include/<exercise> (see the generate recipe).
ifeq ($(strip $(OUT)),)
$(error OUT is not set: make OUT=<out_dir> DRIVER_INCLUDE=<exercises_dir>)
endif
ifeq ($(strip $(DRIVER_INCLUDE)),)
$(error DRIVER_INCLUDE is not set: make OUT=<out_dir> DRIVER_INCLUDE=<exercises_dir>)
endif

# app/ or lib/ -> userspace/ -> <exercise>/
BASE := $(notdir $(abspath $(CURDIR)/../..))

ifeq ($(LINK_TYPE),SO)
NAME := lib$(BASE).so
PIC := -fPIC
LINK_OPTS := -shared -Wl,-soname,$(NAME)
LINK_DEPS :=
else ifeq ($(LINK_TYPE),EXE)
NAME := $(BASE)
PIC :=
LINK_OPTS := -L$(OUT) -l$(BASE)
LINK_DEPS := $(OUT)/lib$(BASE).so
else
$(error LINK_TYPE must be EXE or SO)
endif

COMMON_FLAGS := -g -fvisibility=hidden -Wall -Wextra $(PIC) -I$(DRIVER_INCLUDE) -I$(OUT)/generated/include/$(BASE) -I..
CFLAGS := --std=c17 $(COMMON_FLAGS)
CXXFLAGS := --std=c++20 $(COMMON_FLAGS)

# objects live under $(OUT)/<lib|app>/ so same-named sources in lib/ and app/ cannot collide;
# only the products land at the top of $(OUT)
OBJDIR := $(OUT)/$(notdir $(CURDIR))
SRCS := $(wildcard *.c) $(wildcard *.cpp)
OBJS := $(SRCS:%.c=$(OBJDIR)/%.o)
OBJS := $(OBJS:%.cpp=$(OBJDIR)/%.o)

.PHONY: all clean

all: $(OUT)/$(NAME)

$(OUT)/$(NAME): $(OBJS) $(LINK_DEPS)
	$(CXX) $(CXXFLAGS) -o $@ $(OBJS) $(LINK_OPTS)

$(OBJDIR)/%.o: %.c
	@mkdir -p $(OBJDIR)
	$(CC) $(CFLAGS) -MMD -MP -MJ $@.json -c -o $@ $<

$(OBJDIR)/%.o: %.cpp
	@mkdir -p $(OBJDIR)
	$(CXX) $(CXXFLAGS) -MMD -MP -MJ $@.json -c -o $@ $<

# header dependencies recorded by -MMD, so a regenerated header rebuilds its includers
-include $(OBJS:.o=.d)

clean:
	rm -f $(OUT)/$(NAME) $(OBJS) $(OBJS:%=%.json) $(OBJS:.o=.d)
