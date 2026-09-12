import subprocess, pathlib, json, time, hashlib
root=pathlib.Path('p3-evidence/m1b/verification2')
for name in ['source-inventory','scoped-file-inventory','artifact-hashes']:
 p=pathlib.Path('p3-evidence/m1b/fix1')/(name+'.json')
 data=json.loads(p.read_text())
 (root/(name+'-input.json')).write_bytes(p.read_bytes())
 if isinstance(data,list) and data and 'path' in data[0]:
  checks=[dict(path=x['path'],matches=pathlib.Path(x['path']).exists() and hashlib.sha256(pathlib.Path(x['path']).read_bytes()).hexdigest()==x['sha256']) for x in data]
  (root/(name+'-check.json')).write_text(json.dumps(checks,indent=2))
commands=[('lint','make lint'),('ruff','uv run ruff check src'),('format','uv run ruff format --check src'),('pydoclint','uv run pydoclint src'),('ty','uv run ty check src'),('mypy','uv run mypy src'),('imports','uv run lint-imports'),('unit','uv run pytest --cov=src/huron --cov-report=term-missing'),('coverage','uv run coverage json -o p3-evidence/m1b/verification2/coverage.json'),('radon-cc','uv run radon cc src/huron --min C'),('radon-mi','uv run radon mi src/huron --min B'),('complexipy','uv run complexipy src/huron --max-complexity-allowed 15'),('pyscn','uv run --locked pyscn check src/huron'),('duplication','uv run --locked python scripts/check_duplication.py src/huron'),('docs','make docs'),('diff-check','git diff --check')]
results=[]
for name,cmd in commands:
 print('START',name,flush=True); start=time.time()
 with (root/(name+'.log')).open('w') as f:
  f.write('$ '+cmd+'\n'); f.flush(); p=subprocess.run(cmd,shell=True,stdout=f,stderr=subprocess.STDOUT)
 results.append(dict(name=name,command=cmd,exit=p.returncode,seconds=time.time()-start))
 (root/'static-results.json').write_text(json.dumps(results,indent=2)); print('END',name,p.returncode,flush=True)
