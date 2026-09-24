# generic Makefile for every userspace C/C++ project
# usage: set LINK_TYPE to EXE or SO, then `include ../../../cpp.mk`
#   EXE: builds $(OUT)/<exercise> and links lib<exercise>.so by name
#   SO:  builds $(OUT)/lib<exercise>.so with a matching SONAME
# <exercise> is the name of the directory two levels above this Makefile's
# directory: exercises/<exercise>/userspace/{app,lib}/Makefile.
# Each object also gets a compile_commands fragment, $(OUT)/<obj>.o.json.
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

COMMON_FLAGS := -g -fvisibility=hidden -Wall -Wextra $(PIC) -I$(DRIVER_INCLUDE) -I..
CFLAGS := --std=c17 $(COMMON_FLAGS)
CXXFLAGS := --std=c++20 $(COMMON_FLAGS)

SRCS := $(wildcard *.c) $(wildcard *.cpp)
OBJS := $(SRCS:%.c=$(OUT)/%.o)
OBJS := $(OBJS:%.cpp=$(OUT)/%.o)

.PHONY: all clean

all: $(OUT)/$(NAME)

$(OUT)/$(NAME): $(OBJS) $(LINK_DEPS)
	$(CXX) $(CXXFLAGS) -o $@ $(OBJS) $(LINK_OPTS)

$(OUT)/%.o: %.c
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -MJ $@.json -c -o $@ $<

$(OUT)/%.o: %.cpp
	@mkdir -p $(OUT)
	$(CXX) $(CXXFLAGS) -MJ $@.json -c -o $@ $<

clean:
	rm -f $(OUT)/$(NAME) $(OBJS) $(OBJS:%=%.json)
