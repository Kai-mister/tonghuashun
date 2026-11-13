// Limit the simulator UI service's TCP listeners to the Android loopback interface.
#include <stdint.h>
extern long syscall(long number, ...);
int bind(int fd, const void *address, unsigned length) {
    const uint16_t *family = address;
    unsigned char local[128];
    if (address && (*family == 2 || *family == 10) && length <= sizeof(local)) {
        for (unsigned i = 0; i < length; ++i) local[i] = ((const unsigned char *)address)[i];
        if (*family == 2 && length >= 16) {
            local[4] = 127; local[5] = 0; local[6] = 0; local[7] = 1;
        } else if (*family == 10 && length >= 28) {
            for (unsigned i = 8; i < 24; ++i) local[i] = 0;
            local[23] = 1;
        }
        address = local;
    }
    return (int)syscall(200, fd, address, length); // Linux arm64 __NR_bind
}
