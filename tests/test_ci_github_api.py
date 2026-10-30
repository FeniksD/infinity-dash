import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ci'))
import github_api


class GithubApiTests(unittest.TestCase):
    def setUp(self):
        self.config={'repository':'FeniksD/infinity-dash','repository_id':1440124868,'owner_id':69045720,'approved_head':'a'*40,'workflow_path':'.github/workflows/build.yml','job_name':'Build on VM'}
        self.request={'run_id':123,'attempt':2,'head':'a'*40}
        self.run={'id':123,'run_attempt':2,'event':'workflow_dispatch','head_branch':'main','head_sha':'a'*40,'path':'.github/workflows/build.yml','status':'in_progress','repository':{'id':1440124868},'head_repository':{'id':1440124868},'actor':{'id':69045720},'triggering_actor':{'id':69045720}}
        self.jobs={'jobs':[{'run_id':123,'name':'Build on VM','status':'in_progress','started_at':'now'}],'total_count':1}

    def test_fetches_the_requested_attempt_before_authorizing(self):
        urls=[]
        def get(url):
            urls.append(url)
            return self.jobs if '/jobs?' in url else self.run
        result=github_api.fetch_approved_run(self.config,self.request,get_json=get)
        self.assertEqual(result['id'],123)
        self.assertIn('/attempts/2/jobs?',urls[1])

    def test_stale_attempt_and_wrong_run_are_rejected(self):
        for key in ('id','run_attempt'):
            run=dict(self.run);run[key]=999
            with self.assertRaises(ValueError):
                github_api.fetch_approved_run(self.config,self.request,get_json=lambda url: self.jobs if '/jobs?' in url else run)

    def test_untrusted_repository_path_is_rejected(self):
        self.config['repository']='FeniksD/infinity-dash/../../other'
        with self.assertRaises(ValueError): github_api.fetch_approved_run(self.config,self.request,get_json=lambda url: self.run)

    def test_missing_truncated_and_malformed_job_counts_are_rejected(self):
        for count in (None, True, -1, 0, 2, 101, '1'):
            with self.subTest(count=count):
                jobs=dict(self.jobs,total_count=count)
                with self.assertRaises(ValueError):
                    github_api.fetch_approved_run(self.config,self.request,get_json=lambda url: jobs if '/jobs?' in url else self.run)
