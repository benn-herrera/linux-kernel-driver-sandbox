// SPDX-License-Identifier: GPL-2.0
/*
 * userspace test of matx_mock driver ABI
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
	printf("matx_mock: userspace ok on %s\n", u.release);
	return 0;
}
