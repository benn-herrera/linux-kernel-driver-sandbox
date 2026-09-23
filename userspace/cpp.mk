# generic Makefile that works for every userspace C/C++ project
# usage: `include ../cpp.mk` as sole line of Makefile
ifeq ($(strip $(OUT)),)
$(error OUT is not set: make OUT=<out_dir> DRIVER_INCLUDE=<drivers_dir>)
endif
ifeq ($(strip $(DRIVER_INCLUDE)),)
$(error DRIVER_INCLUDE is not set: make OUT=<out_dir> DRIVER_INCLUDE=<drivers_dir>)
endif

COMMON_FLAGS := -g -Wall -Wextra -I$(DRIVER_INCLUDE)
CFLAGS := --std=c17 $(COMMON_FLAGS)
CXXFLAGS := --std=c++20 $(COMMON_FLAGS)

# executable takes name from containing directory
NAME := $(notdir $(CURDIR))
SRCS := $(wildcard *.c) $(wildcard *.cpp)
OBJS := $(SRCS:%.c=$(OUT)/%.o)
OBJS := $(OBJS:%.cpp=$(OUT)/%.o)

.PHONY: all clean

all: $(OUT)/$(NAME)

$(OUT)/$(NAME): $(OBJS)
	$(CXX) $(CXXFLAGS) -static -o $@ $^

$(OUT)/%.o: %.c
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -c -o $@ $<

$(OUT)/%.o: %.cpp
	@mkdir -p $(OUT)
	$(CXX) $(CXXFLAGS) -c -o $@ $<

clean:
	rm -f $(OUT)/$(NAME) $(OBJS)
