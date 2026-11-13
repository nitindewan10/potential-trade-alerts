"""This repository's own workflow runs: is another watcher already running, and start the hand-over run (a GitHub job
may run at most 6 hours, the market is open 6 h 15 min). Uses the job's own GITHUB_TOKEN; nothing else."""
import os

import net

WORKFLOW = "track.yml"


def _repo():
    return os.environ.get("GITHUB_REPOSITORY", "")


def _h():
    return {"Authorization": "Bearer " + os.environ.get("GITHUB_TOKEN", ""), "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def active_runs():
    """Other runs of this workflow that are in progress (excluding this run)."""
    me = os.environ.get("GITHUB_RUN_ID", "")
    if not _repo() or not os.environ.get("GITHUB_TOKEN"):
        return []
    url = f"https://api.github.com/repos/{_repo()}/actions/workflows/{WORKFLOW}/runs?status=in_progress&per_page=20"
    j = net.retry(lambda: net.request("GET", url, headers=_h()))
    return [r for r in j.get("workflow_runs", []) if str(r.get("id")) != me]


def dispatch(**inputs):
    url = f"https://api.github.com/repos/{_repo()}/actions/workflows/{WORKFLOW}/dispatches"
    body = {"ref": os.environ.get("GITHUB_REF_NAME", "main"), "inputs": {k: str(v).lower() if isinstance(v, bool)
                                                                         else str(v) for k, v in inputs.items()}}
    net.retry(lambda: net.request("POST", url, headers=_h(), body=body, as_json=False))


if __name__ == "__main__":
    # used by the workflow before the memory is loaded:  python3 ghruns.py wait|check
    import sys
    import time
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    out = os.environ.get("GITHUB_OUTPUT")
    skip = False
    try:
        if mode == "wait":  # hand-over run: let the older run finish and save its memory first (max 6 min)
            for _ in range(36):
                if not active_runs():
                    break
                time.sleep(10)
            skip = bool(active_runs())
        else:
            skip = bool(active_runs())
    except Exception as e:  # never block the watcher because the runs list failed
        print("runs check failed:", type(e).__name__)
    print("another tracker is running – this run stops" if skip else "no other tracker running")
    if out:
        with open(out, "a") as fh:
            fh.write(f"skip={'1' if skip else '0'}\n")
