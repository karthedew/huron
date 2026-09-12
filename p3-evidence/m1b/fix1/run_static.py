import subprocess, pathlib, json, time
root=pathlib.Path("p3-evidence/m1b/fix1")
commands=[('lint','make lint'),('ruff','uv run ruff check src'),('format','uv run ruff format --check src'),('pydoclint','uv run pydoclint src'),('ty','uv run ty check src'),('mypy','uv run mypy src'),('imports','uv run lint-imports'),('unit','uv run pytest --cov=src/huron --cov-report=term-missing'),('coverage','uv run coverage json -o p3-evidence/m1b/fix1/coverage.json'),('radon-cc','uv run radon cc src/huron --min C'),('radon-mi','uv run radon mi src/huron --min B'),('complexipy','uv run complexipy src/huron --max-complexity-allowed 15'),('pyscn','uv run --locked pyscn check src/huron'),('duplication','uv run --locked python scripts/check_duplication.py src/huron'),('docs','make docs'),('diff-check','git diff --check'),('native-full-final','uv run --locked pyscn analyze --json src')]
results=[]
for name,cmd in commands:
 print('START',name,flush=True); start=time.time()
 with (root/(name+'.log')).open('w') as f:
  f.write('$ '+cmd+'\n'); f.flush(); p=subprocess.run(cmd,shell=True,stdout=f,stderr=subprocess.STDOUT)
 results.append(dict(name=name,command=cmd,exit=p.returncode,seconds=time.time()-start))
 (root/'static-results.json').write_text(json.dumps(results,indent=2)); print('END',name,p.returncode,flush=True)
