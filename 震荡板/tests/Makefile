CC ?= cc
CFLAGS = -std=c11 -Wall -Wextra -Werror -Wconversion -pedantic -O2
CPPFLAGS = -I../firmware/include

.PHONY: test clean
test: build/test_params
	./build/test_params

build/test_params: test_params.c ../firmware/src/osc_params.c ../firmware/include/osc_params.h
	mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) test_params.c ../firmware/src/osc_params.c -o $@

clean:
	rm -f build/test_params
