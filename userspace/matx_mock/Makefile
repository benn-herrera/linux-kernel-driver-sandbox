ifeq ($(strip $(OUT)),)
$(error OUT is not set: make OUT=<dir>)
endif

CFLAGS := -g -Wall -Wextra

NAME := matx_mock
SRCS := $(wildcard *.c)
OBJS := $(SRCS:%.c=$(OUT)/%.o)

.PHONY: all clean

all: $(OUT)/$(NAME)

$(OUT)/$(NAME): $(OBJS)
	$(CC) $(CFLAGS) -static -o $@ $^

$(OUT)/%.o: %.c
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OUT)/$(NAME) $(OBJS)
