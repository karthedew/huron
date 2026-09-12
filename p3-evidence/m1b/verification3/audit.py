"""Independently bind completed verification to exact source and native scan inventories."""
import json, pathlib, hashlib, re, shutil, sys, fnmatch
sys.path.insert(0,'scripts')
from check_duplication import duplication_report
r=pathlib.Path('p3-evidence/m1b/verification3')
for log,name in [('native-full.log','full-src.json'),('lint.log','native-src.json'),('duplication.log','native-src-huron.json')]:
    announced=re.findall(r'Unified JSON report generated: (\S+)',(r/log).read_text())
    assert len(announced)==1
    shutil.copyfile(announced[0],r/name)
a=json.loads((r/'full-src.json').read_text())
actual={str(p.resolve()) for p in pathlib.Path('src').rglob('*.py')}
scanned={v['file_path'] for v in a['system']['dependency_analysis']['module_metrics'].values()}
v={'actual_files':len(actual),'scanned_files':len(scanned),'missing':sorted(actual-scanned),'unexpected':sorted(scanned-actual),'summary':a['summary'],'errors':{k:a[k].get('errors') for k in ['complexity','dead_code','system']},'max_cognitive_complexity':max(f['metrics']['cognitive_complexity'] for f in a['complexity']['functions']),'native':{}}
assert actual==scanned and a['summary']['skipped_files']==0
assert all(not e for e in v['errors'].values())
assert a['summary']['dead_code_count']==a['summary']['high_complexity_count']==0
assert v['max_cognitive_complexity']<=15
for name in ['full-src.json','native-src.json','native-src-huron.json']:
    d=json.loads((r/name).read_text());v['native'][name]=duplication_report(d)._asdict();req=d['clone']['request']
    assert {str(pathlib.Path(p).resolve()) for p in req['paths']}==actual
    assert not [p for p in req['paths'] if any(fnmatch.fnmatch(p,e) or fnmatch.fnmatch(pathlib.Path(p).name,e) for e in req['exclude_patterns'])]
v['default_exclusions_match_no_source_files']=True
(r/'native-inventory-validation.json').write_text(json.dumps(v,indent=2)+'\n')
s=json.loads((r/'source-inventory-input.json').read_text());scope=json.loads((r/'scoped-file-inventory-input.json').read_text());c=json.loads((r/'coverage.json').read_text())
b=json.load(open('p3-evidence/m1a/verification1/source-hashes-after.json'))
assert all(hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==h for p,h in b.items())
added=[x['path'] for x in s if x['path'] not in b]
out={'source_inventory_sha256':hashlib.sha256((r/'source-inventory-input.json').read_bytes()).hexdigest(),'source_count':len(s),'scope_count':len(scope),'unchanged_baseline_count':len(b),'coverage':c['totals'],'touched_coverage':{p:c['files'][p]['summary'] for p in added}}
for p in s+scope: assert hashlib.sha256(pathlib.Path(p['path']).read_bytes()).hexdigest()==p['sha256']
assert len(added)==17 and all(c['files'][p]['summary']['missing_lines']==0 for p in added)
assert c['totals']['percent_covered']>=95.88
(r/'final-identity-coverage.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
