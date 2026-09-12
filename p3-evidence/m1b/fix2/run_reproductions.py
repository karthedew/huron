import json, os, pathlib, subprocess, time
root=pathlib.Path('p3-evidence/m1b/fix2')
commands=[('verification1','PYTHONPATH=. uv run pytest -q p3-evidence/m1b/verification1/test_review_repro.py')]
for name in ['test_failed_pending_directory_fsync_must_not_leave_record_usable','test_fence_loss_during_pending_clear_must_not_return_success','test_concurrent_same_run_cannot_clear_another_live_installation']:
 commands.append((name,'PYTHONPATH=. uv run pytest -q p3-evidence/m1b/verification2/test_finalization_repro.py::'+name))
results=[]
for name,cmd in commands:
 with (root/(name+'.log')).open('w') as output:
  output.write('$ '+cmd+'\n');output.flush()
  process=subprocess.Popen(cmd,shell=True,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
  try:
   code=process.wait(timeout=20)
  except subprocess.TimeoutExpired:
   import signal
   os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=10)
   code=124
   output.write('\nTimed out: obsolete two-admitted-owner barrier cannot be reached under exclusive ownership.\n')
 results.append(dict(name=name,command=cmd,exit=code))
 (root/'reproduction-results.json').write_text(json.dumps(results,indent=2))
 print(name,code,flush=True)
