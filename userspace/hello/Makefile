# Plain GNU Makefile, not kbuild. CC and OUT come from the caller; nothing is
# written outside OUT.
ifeq ($(strip $(OUT)),)
$(error OUT is not set: make OUT=<dir>)
endif

CFLAGS := -O2 -Wall -Wextra

.PHONY: all clean

all: $(OUT)/hello

$(OUT)/hello: hello.c
	mkdir -p $(OUT)
	$(CC) $(CFLAGS) -static -o $@ $<

clean:
	rm -f $(OUT)/hello
