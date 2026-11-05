import hashlib,json,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2]
out=Path(__file__).resolve().parent/'mvp-3x3-20261105'
files=[root/'config.json',root/'agent.py',root/'evaluate_course.py',*sorted((root/'course_agent').glob('*.py'))]
def fingerprint(): return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
initial=fingerprint()
state={'status':'running','fingerprint':initial,'runs':[],'automatic_retries':False}
def save():
 p=out/'batch.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2));tmp.replace(p)
save()
for index in range(1,4):
 for stage in ('paper','source'):
  if fingerprint()!=initial: state['status']='blocked_code_changed';save();sys.exit(2)
  name=f'{stage}-{index:02d}';entry={'name':name,'stage':stage,'index':index,'status':'running','started':time.time()};state['runs'].append(entry);save()
  print('START '+name,flush=True)
  with (out/(name+'.log')).open('w') as log:
   rc=subprocess.call([sys.executable,str(root/'evaluate_course.py'),'--run-paid','--stage',stage,'--request-limit',str(40 if stage=='paper' else 20)],cwd=root,stdout=log,stderr=subprocess.STDOUT)
  entry.update(status='finished',exit_code=rc,seconds=round(time.time()-entry['started'],2))
  for line in (out/(name+'.log')).read_text(errors='replace').splitlines():
   if line.startswith('Archive destination: '):entry['archive']=line.split(': ',1)[1]
   if line.startswith('Native run: '):entry['native']=line.split(': ',1)[1]
  save();print('FINISH '+name+' exit='+str(rc),flush=True)
  if rc not in (0,1):state['status']='infrastructure_failure';save();sys.exit(rc)
state['status']='completed';save();print('BATCH COMPLETE',flush=True)
