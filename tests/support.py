import atexit, importlib.util, json, os, shutil, tempfile
BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("bot_config", os.path.join(BOT, "config.py"))
config_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(config_module)
CONFIG = config_module.values()
os.makedirs(CONFIG["SCRATCH_ROOT"], exist_ok=True)
# Logged in every isolated guard's ledger; TAG prefixes commands that must carry a job id.
JOB = "261031-0a0b0c"
TAG = f"env FABRIC_JOB={JOB} "


def render(text, json_escaped=False, config=None):
    return config_module.render(text, config or CONFIG, json_escaped)


def isolated_guard(lock_holder="abc"):
    """A guard copy with its own scratch root and session registry, so tests never see or change a running bot's VM lock or builds.
    Returns (guard path, config, registry directory). Session lock_holder is registered as running and holds the Editor lock."""
    root = tempfile.mkdtemp(dir=CONFIG["SCRATCH_ROOT"])
    atexit.register(shutil.rmtree, root, True)
    # The guard protects its own folder, so scratch lives beside it rather than in it.
    copy, temp, registry = (os.path.join(root, name) for name in ("bot", "temp", "sessions"))
    jobs = os.path.join(root, "jobs.jsonl")
    with open(jobs, "w") as handle:
        handle.write(json.dumps({"event": "start", "id": JOB, "time": 1793400000, "user": "tester", "user_id": "111111111111111111", "text": "build main"}) + "\n")
    scratch = os.path.join(temp, CONFIG["PROJECT_SLUG"])
    for folder in (copy, temp, scratch, registry):
        os.mkdir(folder)
    for name in ("guard.py", "config.py"):
        shutil.copy(os.path.join(BOT, name), copy)
    with open(os.path.join(BOT, ".envrc")) as source, open(os.path.join(copy, ".envrc"), "w") as handle:
        handle.write(source.read() + f'\nexport FABRIC_BOT_TEMP_ROOT="{temp}"\nexport FABRIC_BOT_SESSION_REGISTRY="{registry}"\n'
                     f'export FABRIC_BOT_JOBS_FILE="{jobs}"\nexport FABRIC_BOT_JOBS_LOCAL_FILE="{root}/jobs-local.jsonl"\n')
    task_root = os.path.join(scratch, "discord-bot")
    config = dict(CONFIG, TEMP_ROOT=temp, SCRATCH_ROOT=scratch, SESSION_REGISTRY=registry, TASK_ROOT=task_root,
                  EDITOR_LOCK=os.path.join(task_root, "editor.lock"), JOBS_FILE=jobs, JOBS_LOCAL_FILE=f"{root}/jobs-local.jsonl")
    if lock_holder:
        register_session(registry, lock_holder)
        os.makedirs(config["EDITOR_LOCK"])
        with open(os.path.join(config["EDITOR_LOCK"], "holder.json"), "w") as handle:
            json.dump({"session": lock_holder, "agent": "", "taken": "test"}, handle)
    return os.path.join(copy, "guard.py"), config, registry


def register_session(registry, session_id, pid=None):
    with open(os.path.join(registry, f"{session_id}.json"), "w") as handle:
        json.dump({"pid": pid or os.getpid(), "sessionId": session_id}, handle)
