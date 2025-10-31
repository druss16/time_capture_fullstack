#include <mach-o/dyld.h>
#include <unistd.h>
#include <libgen.h>
#include <limits.h>
#include <stdio.h>
#include <stdint.h>
int main(int argc, char *argv[]) {
    char exePath[PATH_MAX];
    uint32_t size = sizeof(exePath);
    if (_NSGetExecutablePath(exePath, &size) != 0) { perror("_NSGetExecutablePath"); return 1; }
    char *macosDir = dirname(exePath);
    char target[PATH_MAX];
    snprintf(target, sizeof(target),
             "%s/../Resources/TimeTrackerAgent/TimeTrackerAgent", macosDir);
    execv(target, argv);
    perror("execv");
    return 1;
}
