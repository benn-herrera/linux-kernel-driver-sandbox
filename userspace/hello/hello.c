// SPDX-License-Identifier: GPL-2.0
/*
 * hello: smoke program proving the static userspace build and staging path.
 */

#include <stdio.h>
#include <sys/utsname.h>

int main(void)
{
	struct utsname u;

	if (uname(&u) != 0) {
		perror("uname");
		return 1;
	}
	printf("hello: userspace ok on %s\n", u.release);
	return 0;
}
