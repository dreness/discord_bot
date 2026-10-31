// PreToolUse hook entry point: forwards the payload, environment and working directory to the guard server, and
// runs guard.py directly when the server is unreachable, doesn't finish the check, or doesn't answer in time. Denies
// when guard.py doesn't finish either, so the call only proceeds on an answer from the guard.
// Usage: guard-client <socket> <guard.py> [timeout seconds, for each of the two attempts]
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;

// Applies to the server and then to the local guard.py. Above the guard's slowest check (gh api, 20 s). Both
// attempts together stay under the hook timeout in settings.json, so the client's deny and its reason come first.
#define TIMEOUT_SECONDS 30

typedef struct {
    char *bytes;
    size_t length, capacity;
} Buffer;

static void append(Buffer *buffer, const void *bytes, size_t length) {
    if (buffer->length + length > buffer->capacity) {
        buffer->capacity = (buffer->length + length) * 2 + 4096;
        buffer->bytes = realloc(buffer->bytes, buffer->capacity);
        if (!buffer->bytes) exit(1);
    }
    memcpy(buffer->bytes + buffer->length, bytes, length);
    buffer->length += length;
}

static void append_length(Buffer *buffer, size_t length) {
    uint8_t bytes[4] = {length >> 24, length >> 16, length >> 8, length};
    append(buffer, bytes, 4);
}

static int write_all(int descriptor, const char *bytes, size_t length) {
    while (length > 0) {
        ssize_t written = write(descriptor, bytes, length);
        if (written <= 0) return -1;
        bytes += written;
        length -= written;
    }
    return 0;
}

// Returns -1 if reading stopped on an error instead of end of file.
static int read_all(int descriptor, Buffer *buffer) {
    char chunk[65536];
    ssize_t count;
    while ((count = read(descriptor, chunk, sizeof chunk)) > 0) append(buffer, chunk, count);
    return count < 0 ? -1 : 0;
}

static double now(void) {
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC, &time);
    return time.tv_sec + time.tv_nsec / 1e9;
}

// For a non-blocking descriptor: waits until it's ready for events, or returns -1 at the deadline.
static int wait_until(int descriptor, short events, double deadline) {
    for (;;) {
        double remaining = deadline - now();
        if (remaining <= 0) return -1;
        struct pollfd entry = {.fd = descriptor, .events = events};
        int ready = poll(&entry, 1, (int)(remaining * 1000) + 1);
        if (ready > 0) return 0;
        if (ready < 0 && errno != EINTR) return -1;
    }
}

static int send_before(int descriptor, const char *bytes, size_t length, double deadline) {
    while (length > 0) {
        if (wait_until(descriptor, POLLOUT, deadline) != 0) return -1;
        ssize_t written = write(descriptor, bytes, length);
        if (written < 0 && (errno == EAGAIN || errno == EINTR)) continue;
        if (written <= 0) return -1;
        bytes += written;
        length -= written;
    }
    return 0;
}

static int receive_before(int descriptor, Buffer *buffer, double deadline) {
    char chunk[65536];
    for (;;) {
        if (wait_until(descriptor, POLLIN, deadline) != 0) return -1;
        ssize_t count = read(descriptor, chunk, sizeof chunk);
        if (count < 0 && (errno == EAGAIN || errno == EINTR)) continue;
        if (count < 0) return -1;
        if (count == 0) return 0;
        append(buffer, chunk, count);
    }
}

static int ask_server(const char *socket_path, const Buffer *payload, int timeout_seconds) {
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    if (strlen(socket_path) >= sizeof address.sun_path) return -1;
    strcpy(address.sun_path, socket_path);
    double deadline = now() + timeout_seconds;
    int connection = socket(AF_UNIX, SOCK_STREAM, 0);
    if (connection < 0) return -1;
    // Connecting to a full backlog fails right away, but a stopped server still completes connects into a backlog
    // with room, then never reads or replies.
    if (connect(connection, (struct sockaddr *)&address, sizeof address) != 0 ||
        fcntl(connection, F_SETFL, fcntl(connection, F_GETFL) | O_NONBLOCK) != 0) {
        close(connection);
        return -1;
    }

    Buffer request = {0}, environment = {0};
    for (char **entry = environ; *entry; entry++) append(&environment, *entry, strlen(*entry) + 1);
    append_length(&request, environment.length);
    append(&request, environment.bytes, environment.length);
    char directory[4096];
    if (!getcwd(directory, sizeof directory)) directory[0] = 0;
    append_length(&request, strlen(directory));
    append(&request, directory, strlen(directory));
    append(&request, payload->bytes, payload->length);
    if (send_before(connection, request.bytes, request.length, deadline) != 0) {
        close(connection);
        return -1;
    }
    shutdown(connection, SHUT_WR);

    Buffer reply = {0};
    int status = receive_before(connection, &reply, deadline);
    close(connection);
    if (status != 0 || reply.length == 0 || reply.bytes[0] != '=') return -1;
    write_all(STDOUT_FILENO, reply.bytes + 1, reply.length - 1);
    return 0;
}

// Runs guard.py on the payload and copies its decision to stdout. Returns -1 without output if python3 is missing,
// guard.py crashes or exits nonzero, or it doesn't finish by the deadline.
static int run_guard(const char *guard, const Buffer *payload, int timeout_seconds) {
    int input[2], output[2];
    if (pipe(input) != 0) return -1;
    if (pipe(output) != 0) return -1;
    pid_t child = fork();
    if (child < 0) return -1;
    if (child == 0) {
        dup2(input[0], STDIN_FILENO);
        dup2(output[1], STDOUT_FILENO);
        close(input[0]), close(input[1]), close(output[0]), close(output[1]);
        execlp("python3", "python3", "-I", guard, (char *)NULL);
        _exit(127);
    }
    close(input[0]), close(output[1]);
    double deadline = now() + timeout_seconds;
    fcntl(input[1], F_SETFL, fcntl(input[1], F_GETFL) | O_NONBLOCK);
    fcntl(output[0], F_SETFL, fcntl(output[0], F_GETFL) | O_NONBLOCK);
    // guard.py reads all of its input before it writes anything.
    Buffer decision = {0};
    int status = send_before(input[1], payload->bytes, payload->length, deadline);
    close(input[1]);
    if (status == 0) status = receive_before(output[0], &decision, deadline);
    close(output[0]);
    int exit_status = 0;
    while (status == 0) {
        pid_t done = waitpid(child, &exit_status, WNOHANG);
        if (done == child) break;
        if (done < 0 && errno != EINTR) status = -1;
        else if (now() >= deadline) status = -1;
        else usleep(1000);
    }
    if (status != 0) {
        kill(child, SIGKILL);
        waitpid(child, NULL, 0);
        return -1;
    }
    if (!WIFEXITED(exit_status) || WEXITSTATUS(exit_status) != 0) return -1;
    write_all(STDOUT_FILENO, decision.bytes, decision.length);
    return 0;
}

// The hook's onFailure blocks the call on any other failure too, but without telling Claude why.
static int deny(const char *reason) {
    printf("{\"hookSpecificOutput\": {\"hookEventName\": \"PreToolUse\", \"permissionDecision\": \"deny\", "
           "\"permissionDecisionReason\": \"discord-bot guard: %s; this call is denied. Tell the requester the operator has to fix the guard\"}}\n", reason);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 3 && argc != 4) return deny("usage: guard-client <socket> <guard.py> [timeout seconds]");
    int timeout_seconds = argc == 4 ? atoi(argv[3]) : TIMEOUT_SECONDS;
    if (timeout_seconds <= 0) return deny("timeout must be a positive number of seconds");
    signal(SIGPIPE, SIG_IGN);
    Buffer payload = {0};
    if (read_all(STDIN_FILENO, &payload) != 0) return deny("reading the hook payload failed");
    if (ask_server(argv[1], &payload, timeout_seconds) == 0) return 0;
    if (run_guard(argv[2], &payload, timeout_seconds) == 0) return 0;
    return deny("guard.py didn't finish the check");
}
