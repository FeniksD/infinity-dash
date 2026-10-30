"""Read public GitHub run evidence; never trust equivalent client-supplied JSON."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from run_policy import validate_run


class GithubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        target=urllib.parse.urlparse(newurl)
        if target.scheme!='https' or target.netloc!='api.github.com':
            raise ValueError('GitHub API redirected outside its trusted host')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def get_json(url):
    if not url.startswith('https://api.github.com/repos/'):
        raise ValueError('unexpected API URL')
    request=urllib.request.Request(url,headers={'User-Agent':'infinity-dash-build-gateway','Accept':'application/vnd.github+json'})
    opener=urllib.request.build_opener(GithubRedirect())
    try:
        with opener.open(request,timeout=15) as response:
            data=response.read(1024*1024+1)
        if len(data)>1024*1024: raise ValueError('GitHub response too large')
        return json.loads(data)
    except (urllib.error.URLError,UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError('GitHub run evidence could not be verified') from exc


def fetch_approved_run(config,request,get_json=get_json):
    repo=config['repository']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):
        raise ValueError('invalid trusted repository name')
    run_id,attempt=request['run_id'],request['attempt']
    if type(run_id) is not int or not 1<=run_id<2**63 or type(attempt) is not int or not 1<=attempt<=1000:
        raise ValueError('invalid requested run identity')
    base=f'https://api.github.com/repos/{repo}/actions/runs/{run_id}'
    run=get_json(base)
    if not isinstance(run,dict) or run.get('id')!=run_id or run.get('run_attempt')!=attempt or run.get('head_sha')!=request.get('head'):
        raise ValueError('requested GitHub run does not match API evidence')
    response=get_json(f'{base}/attempts/{attempt}/jobs?per_page=100')
    if not isinstance(response,dict) or not isinstance(response.get('jobs'),list):
        raise ValueError('invalid or incomplete GitHub job evidence')
    count=response.get('total_count')
    if type(count) is not int or not 0<=count<=100 or len(response['jobs'])!=count:
        raise ValueError('invalid or incomplete GitHub job evidence')
    validate_run(run,response['jobs'],config)
    return run
