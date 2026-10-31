#!/usr/bin/env python3 -I
"""The job ledger: one line per Discord request and per result, kept on the Cua Volume (JOBS_FILE), or in
JOBS_LOCAL_FILE while the volume isn't mounted (moved to the volume by the next start that finds it mounted).
  jobs.py start <message id>                       log a request; prints its job id. Sender and text come from the
                                                   session's transcript, not the command line.
  jobs.py finish <job id> <status> <file>          record the result (the final reply's text, read from <file>)
  jobs.py list [<user id>] [<offset>]              the 10 most recent jobs from <offset> back, newest first
  jobs.py show <job id>                            one job: request, status, result
  jobs.py running                                  processes tagged FABRIC_JOB=<job id>, by job
The bot may run these (settings.json, guard.py) but not read this file or the ledger."""
import glob
import importlib.util
import json
import os
import re
import secrets
import sys
import time

JOB_ID = re.compile(r"[0-9]{6}-[0-9a-f]{6}")
MESSAGE_ID = re.compile(r"[0-9]{15,21}")
STATUSES = ("done", "failed", "blocked", "cancelled")
CHANNEL_TAG = re.compile(r'<channel source="plugin:discord:discord"([^>]*)>')
TAG_ATTRIBUTE = re.compile(r'(\w+)="([^"]*)"')
ENVIRONMENT_NAME = "FABRIC_JOB"
MAXIMUM_RESULT_BYTES = 16384
TRANSCRIPTS_SEARCHED = 3
# Requests too small to be worth listing; they are still logged.
PAGE = 10
ROUTINE = {"help", "quota", "clear", "editor status", "status"}
USAGE = __doc__.split("\n", 2)[2].split("The bot may")[0].rstrip()


def load_config():
    spec = importlib.util.spec_from_file_location("bot_config", os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.values()


class Ledger:
    def __init__(self, path, local_path, volume):
        self.path, self.local_path, self.volume = path, local_path, volume

    def mounted(self):
        return os.path.ismount(self.volume)

    def lines(self):
        events = []
        for path in (self.path, self.local_path):
            try:
                with open(path) as handle:
                    for line in handle:
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(event, dict) and JOB_ID.fullmatch(str(event.get("id", ""))):
                            events.append(event)
            except OSError:
                pass
        return events

    def jobs(self):
        """Job id -> the start event, with the latest result's fields merged in; oldest first."""
        jobs = {}
        for event in sorted(self.lines(), key=lambda event: event.get("time", 0)):
            if event.get("event") == "start":
                jobs.setdefault(event["id"], dict(event))
            elif event.get("event") == "finish" and event["id"] in jobs:
                jobs[event["id"]].update(status=event.get("status"), result=event.get("result"), finished=event.get("time"))
        return jobs

    def append(self, event):
        """Returns where it went: 'volume' or 'local'."""
        path, where = (self.path, "volume") if self.mounted() else (self.local_path, "local")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if where == "volume":
            self.move_local()
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, (json.dumps(event, sort_keys=True) + "\n").encode())
        finally:
            os.close(descriptor)
        return where

    def move_local(self):
        try:
            with open(self.local_path) as handle:
                text = handle.read()
        except OSError:
            return
        if text:
            with open(self.path, "a") as handle:
                handle.write(text if text.endswith("\n") else text + "\n")
        os.remove(self.local_path)


def find_message(transcript_directory, message_id):
    """The Discord message's tag attributes and text, from this project's newest transcripts."""
    transcripts = sorted(glob.glob(os.path.join(transcript_directory, "*.jsonl")), key=os.path.getmtime, reverse=True)
    needle = f'message_id=\\"{message_id}\\"'
    for transcript in transcripts[:TRANSCRIPTS_SEARCHED]:
        with open(transcript, errors="replace") as handle:
            for line in handle:
                if needle not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                content = entry.get("content") if entry.get("type") == "queue-operation" else (entry.get("message") or {}).get("content") if entry.get("type") == "user" else None
                if isinstance(content, list):
                    content = "".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
                if not isinstance(content, str):
                    continue
                tag = CHANNEL_TAG.match(content.lstrip())
                if not tag:
                    continue
                attributes = dict(TAG_ATTRIBUTE.findall(tag.group(1)))
                if attributes.get("message_id") != message_id:
                    continue
                text = content.lstrip()[tag.end():]
                text = text[:text.rfind("</channel>")] if "</channel>" in text else text
                return attributes, text.strip()
    return None


def new_id(existing, now):
    while True:
        job_id = time.strftime("%y%m%d", time.gmtime(now)) + "-" + secrets.token_hex(3)
        if job_id not in existing:
            return job_id


def excerpt(text, length=80):
    text = " ".join((text or "").split())
    return text if len(text) <= length else text[:length - 3] + "..."


def stamp(seconds):
    return f"<t:{int(seconds)}:f>" if seconds else "?"


def describe(job):
    status = job.get("status") or "no result recorded"
    return f"job {job['id']} - {job.get('user', '?')} ({job.get('user_id', '?')}), {stamp(job.get('time'))}, {status}: \"{excerpt(job.get('text'))}\""


def is_routine(job):
    return " ".join(re.sub(r"<@!?[0-9]+>", "", job.get("text") or "").lower().split()).strip(" .!?") in ROUTINE


# Processes

def process_environments():
    """pid -> (parent pid, executable name, FABRIC_JOB value) for this user's processes that carry one."""
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    count = libc.proc_listallpids(None, 0)
    pids = (ctypes.c_int * (count + 64))()
    count = libc.proc_listallpids(pids, ctypes.sizeof(pids))
    buffer = ctypes.create_string_buffer(1 << 20)
    info = ctypes.create_string_buffer(136)
    tagged = {}
    prefix = (ENVIRONMENT_NAME + "=").encode()
    for pid in pids[:max(count, 0)]:
        name = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
        size = ctypes.c_size_t(ctypes.sizeof(buffer))
        if pid <= 0 or libc.sysctl(name, 3, buffer, ctypes.byref(size), None, 0) != 0 or size.value < 4:
            continue
        raw = ctypes.string_at(buffer, size.value)
        argument_count = int.from_bytes(raw[:4], "little")
        executable, _, rest = raw[4:].partition(b"\0")
        strings = rest.lstrip(b"\0").split(b"\0")
        job = next((string[len(prefix):].decode(errors="replace") for string in strings[argument_count:] if string.startswith(prefix)), None)
        if job is None:
            continue
        # PROC_PIDTBSDINFO; the parent pid is at offset 16.
        parent = int.from_bytes(info.raw[16:20], "little") if libc.proc_pidinfo(pid, 3, ctypes.c_uint64(0), info, 136) == 136 else None
        tagged[pid] = (parent, executable.decode(errors="replace").rsplit("/", 1)[-1], job)
    return tagged


def running_jobs(tagged=None):
    """Job id -> [(pid, executable)] for the outermost tagged processes of each job."""
    tagged = process_environments() if tagged is None else tagged
    jobs = {}
    for pid, (parent, executable, job) in sorted(tagged.items()):
        if parent in tagged and tagged[parent][2] == job:
            continue
        jobs.setdefault(job, []).append((pid, executable))
    return jobs


def describe_running(running, jobs):
    lines = []
    for job_id, processes in running.items():
        job = jobs.get(job_id) or {"id": job_id, "text": "(not in the ledger)"}
        names = ", ".join(f"{executable} (pid {pid})" for pid, executable in processes[:6]) + (f" and {len(processes) - 6} more" if len(processes) > 6 else "")
        lines.append(f"{describe(job)} - {names}")
    return lines


def blocking_jobs(requester, running, jobs):
    """Running jobs that aren't the requester's (or aren't in the ledger)."""
    return {job_id: processes for job_id, processes in running.items() if (jobs.get(job_id) or {}).get("user_id") != requester}


# Commands

def run(arguments, ledger, transcript_directory, scratch_root, now, tagged=None):
    """Returns (output, exit status)."""
    command, rest = (arguments[0], arguments[1:]) if arguments else ("", [])
    if command == "start" and len(rest) == 1 and MESSAGE_ID.fullmatch(rest[0]):
        jobs = ledger.jobs()
        known = next((job for job in jobs.values() if job.get("message_id") == rest[0]), None)
        if known:
            return f"job {known['id']} (already logged)", 0
        found = find_message(transcript_directory, rest[0])
        if not found:
            return f"not logged: no Discord message {rest[0]} in this session's transcript", 1
        attributes, text = found
        job_id = new_id(jobs, now)
        event = {"event": "start", "id": job_id, "time": int(now), "message_ts": attributes.get("ts"), "user": attributes.get("user"),
                 "user_id": attributes.get("user_id"), "chat_id": attributes.get("chat_id"), "message_id": rest[0], "text": text}
        where = ledger.append(event)
        return f"job {job_id}" + ("" if where == "volume" else " (logged locally: Cua Volume not mounted)"), 0
    if command == "finish" and len(rest) == 3 and JOB_ID.fullmatch(rest[0]) and rest[1] in STATUSES:
        job_id, status, path = rest
        if rest[0] not in ledger.jobs():
            return f"not recorded: no job {job_id}", 1
        real = os.path.realpath(path)
        if not real.startswith(os.path.realpath(scratch_root) + os.sep) or not os.path.isfile(real):
            return f"not recorded: the result file must be a file under {scratch_root}", 2
        with open(real, "rb") as handle:
            data = handle.read(MAXIMUM_RESULT_BYTES + 1)
        if len(data) > MAXIMUM_RESULT_BYTES:
            return f"not recorded: the result is over {MAXIMUM_RESULT_BYTES} bytes; put the detail in the report gist and record the summary", 1
        where = ledger.append({"event": "finish", "id": job_id, "time": int(now), "status": status, "result": data.decode(errors="replace").strip()})
        return f"recorded {status} for job {job_id}" + ("" if where == "volume" else " (locally: Cua Volume not mounted)"), 0
    if command == "list" and len(rest) <= 2:
        user, offset = None, 0
        for argument in rest:
            if MESSAGE_ID.fullmatch(argument) and user is None:
                user = argument
            elif re.fullmatch(r"[0-9]{1,5}", argument):
                offset = int(argument)
            else:
                return USAGE, 2
        jobs = [job for job in reversed(list(ledger.jobs().values())) if not is_routine(job) and (user is None or job.get("user_id") == user)]
        page = jobs[offset:offset + PAGE]
        if not page:
            return ("no jobs logged" if not jobs else f"no jobs past the {len(jobs)} logged") + (f" for {user}" if user else ""), 0
        lines = [describe(job) for job in page]
        if offset + PAGE < len(jobs):
            lines.append(f"({len(jobs) - offset - PAGE} older; offset {offset + PAGE} for the next {PAGE})")
        return "\n".join(lines), 0
    if command == "show" and len(rest) == 1 and JOB_ID.fullmatch(rest[0]):
        job = ledger.jobs().get(rest[0])
        if not job:
            return f"no job {rest[0]}", 1
        lines = [describe(job), "request:", job.get("text") or ""]
        if job.get("status"):
            lines += [f"result ({job['status']}, {stamp(job.get('finished'))}):", job.get("result") or ""]
        return "\n".join(lines), 0
    if command == "running" and not rest:
        running = running_jobs(tagged)
        return "\n".join(describe_running(running, ledger.jobs())) or "no tagged processes running", 0
    return USAGE, 2


def ledger_from(config):
    return Ledger(config["JOBS_FILE"], config["JOBS_LOCAL_FILE"], config["CUA_VOLUME"])


def main():
    config = load_config()
    output, status = run(sys.argv[1:], ledger_from(config), config["TRANSCRIPT_DIRECTORY"], config["SCRATCH_ROOT"], time.time())
    print(output)
    sys.exit(status)


if __name__ == "__main__":
    main()
