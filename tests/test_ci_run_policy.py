import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_policy", ROOT / "ci/run_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class RunPolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = {"repository_id":1440124868,"owner_id":69045720,"approved_head":"a"*40,"workflow_path":".github/workflows/build.yml","job_name":"Build on VM"}
        self.run = {"id":123,"run_attempt":1,"repository":{"id":1440124868},"head_repository":{"id":1440124868},"actor":{"id":69045720},"triggering_actor":{"id":69045720},"event":"workflow_dispatch","head_branch":"main","head_sha":"a"*40,"path":".github/workflows/build.yml","status":"in_progress"}
        self.jobs = [{"run_id":123,"name":"Build on VM","status":"in_progress","started_at":"2026-10-30T20:00:00Z"}]

    def test_expected_owner_manual_run_is_allowed(self):
        policy.validate_run(self.run, self.jobs, self.config)

    def test_non_owner_and_non_owner_rerun_are_rejected(self):
        for field in ("actor", "triggering_actor"):
            run=copy.deepcopy(self.run)
            run[field]["id"]=7
            with self.assertRaises(ValueError): policy.validate_run(run,self.jobs,self.config)

    def test_fork_push_wrong_branch_and_unapproved_commit_are_rejected(self):
        for field, value in (("event","pull_request"),("event","push"),("head_branch","feature"),("head_sha","b"*40),("path",".github/workflows/other.yml")):
            run=copy.deepcopy(self.run); run[field]=value
            with self.assertRaises(ValueError): policy.validate_run(run,self.jobs,self.config)
        run=copy.deepcopy(self.run); run["head_repository"]["id"]=7
        with self.assertRaises(ValueError): policy.validate_run(run,self.jobs,self.config)

    def test_waiting_for_approval_or_wrong_job_is_rejected(self):
        for field,value in (("status","queued"),("started_at",None),("name","Untrusted job"),("run_id",124)):
            jobs=copy.deepcopy(self.jobs); jobs[0][field]=value
            with self.assertRaises(ValueError): policy.validate_run(self.run,jobs,self.config)

    def test_malformed_api_metadata_is_rejected(self):
        with self.assertRaises(ValueError): policy.validate_run(None,self.jobs,self.config)
        run=copy.deepcopy(self.run); run["repository"]=None
        with self.assertRaises(ValueError): policy.validate_run(run,self.jobs,self.config)
        with self.assertRaises(ValueError): policy.validate_run(self.run,None,self.config)
