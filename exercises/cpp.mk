# generic Makefile for every userspace C/C++ project
# usage: set LINK_TYPE to EXE or SO, then `include ../../../cpp.mk`
#   EXE: builds $(OUT)/<dir> (the including Makefile's directory, app_cpp) and links lib<exercise>.so by name
#   SO:  builds $(OUT)/lib<exercise>.so with a matching SONAME
# <exercise> is the name of the directory two levels above this Makefile's
# directory: exercises/<exercise>/userspace/{app_cpp,lib}/Makefile.
# Each object also gets a compile_commands fragment, $(OUT)/obj/<lib|app_cpp>/<obj>.o.json.
# Generated headers are found at $(OUT)/generated/include/<exercise> (see the generate recipe).
ifeq ($(strip $(OUT)),)
$(error OUT is not set: make OUT=<out_dir> DRIVER_INCLUDE=<exercises_dir>)
endif
ifeq ($(strip $(DRIVER_INCLUDE)),)
$(error DRIVER_INCLUDE is not set: make OUT=<out_dir> DRIVER_INCLUDE=<exercises_dir>)
endif

# app_cpp/ or lib/ -> userspace/ -> <exercise>/
BASE := $(notdir $(abspath $(CURDIR)/../..))

ifeq ($(LINK_TYPE),SO)
NAME := lib$(BASE).so
PIC := -fPIC
LINK_OPTS := -shared -Wl,-soname,$(NAME)
LINK_DEPS :=
else ifeq ($(LINK_TYPE),EXE)
# the test program is named after its directory (app_cpp): one exercise is staged per boot,
# so the exercise name disambiguates nothing there, and the library alone carries it
NAME := $(notdir $(CURDIR))
PIC :=
LINK_OPTS := -L$(OUT) -l$(BASE)
LINK_DEPS := $(OUT)/lib$(BASE).so
else
$(error LINK_TYPE must be EXE or SO)
endif

COMMON_FLAGS := -g -fvisibility=hidden -Wall -Wextra $(PIC) -I$(DRIVER_INCLUDE) -I$(OUT)/generated/include/$(BASE)
CFLAGS := --std=c17 $(COMMON_FLAGS)
CXXFLAGS := --std=c++20 $(COMMON_FLAGS)

# objects live under $(OUT)/obj/<lib|app_cpp>/ so same-named sources in lib/ and app_cpp/ cannot
# collide and no object directory shares a path with the product app_cpp; only the products land at
# the top of $(OUT)
OBJDIR := $(OUT)/obj/$(notdir $(CURDIR))
SRCS := $(wildcard *.c) $(wildcard *.cpp)
OBJS := $(SRCS:%.c=$(OBJDIR)/%.o)
OBJS := $(OBJS:%.cpp=$(OBJDIR)/%.o)

.PHONY: all

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
