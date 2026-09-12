import subprocess, pathlib, os, json, time
root=pathlib.Path('p3-evidence/m1b/verification2')
info=json.loads(subprocess.check_output(['podman','machine','inspect']))[0]
with (root/'podman-start.log').open('w') as f:
 if info['State']!='running': subprocess.run(['podman','machine','start'],stdout=f,stderr=subprocess.STDOUT,check=True)
for attempt in range(60):
 if subprocess.run(['podman','info'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0: break
 time.sleep(1)
else: raise RuntimeError('Podman readiness failed')
info=json.loads(subprocess.check_output(['podman','machine','inspect']))[0]
os.environ.update(DOCKER_HOST='unix://'+info['ConnectionInfo']['PodmanSocket']['Path'],TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE='/run/podman/podman.sock',TESTCONTAINERS_RYUK_DISABLED='true')
(root/'podman-inspect.json').write_text(json.dumps(info,indent=2))
results=[]
for name,cmd in [('contract','uv run pytest -m contract'),('integration','uv run pytest -m integration -s'),('acceptance','make test-acceptance')]:
 print('START',name,flush=True); start=time.time()
 with (root/(name+'.log')).open('w') as f:
  f.write('$ '+cmd+'\n');f.flush(); p=subprocess.run(cmd,shell=True,stdout=f,stderr=subprocess.STDOUT)
 results.append(dict(name=name,command=cmd,exit=p.returncode,seconds=time.time()-start))
 (root/'services-results.json').write_text(json.dumps(results,indent=2));print('END',name,p.returncode,flush=True)
with (root/'podman-final-containers.log').open('w') as f: subprocess.run(['podman','ps','-a'],stdout=f,stderr=subprocess.STDOUT)

with (root/'linux-cleanup.log').open('w') as f: subprocess.run(['podman','machine','ssh','sudo ls -d /var/lib/huron-controlled-test-* /run/huron-controller-test-*'],stdout=f,stderr=subprocess.STDOUT)
