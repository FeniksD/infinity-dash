"""Owner-only policy for a future restricted VM trigger; no network or execution."""
import re


def validate_run(run, jobs, config):
    """Reject runs that are not the approved owner's active manual workflow."""
    if not isinstance(run, dict) or not isinstance(jobs, list):
        raise ValueError("invalid GitHub API metadata")
    owner = config["owner_id"]
    repository = config["repository_id"]
    head = config["approved_head"]
    if type(owner) is not int or type(repository) is not int or not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("invalid trusted run policy")
    expected = {
        "event": "workflow_dispatch", "head_branch": "main", "head_sha": head,
        "path": config["workflow_path"], "status": "in_progress",
    }
    for field, value in expected.items():
        if run.get(field) != value:
            raise ValueError("unapproved workflow run: " + field)
    for field in ("repository", "head_repository"):
        value = run.get(field)
        if not isinstance(value, dict) or value.get("id") != repository:
            raise ValueError("workflow repository is not approved")
    for field in ("actor", "triggering_actor"):
        value = run.get(field)
        if not isinstance(value, dict) or value.get("id") != owner:
            raise ValueError("workflow initiator is not the owner")
    if type(run.get("id")) is not int or type(run.get("run_attempt")) is not int or run["run_attempt"] < 1:
        raise ValueError("invalid workflow run identity")
    active = [j for j in jobs if isinstance(j, dict) and j.get("name") == config["job_name"] and j.get("run_id") == run["id"] and j.get("status") == "in_progress" and j.get("started_at")]
    if len(active) != 1:
        raise ValueError("approved build job has not started (approval may still be pending)")
