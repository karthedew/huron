"""Record exact source, scope, coverage and complete native-analysis identities."""
import hashlib
import json
import re
from pathlib import Path

from scripts.check_duplication import duplication_report

root = Path('p3-evidence/m1b/fix1')

def save(name, value):
    (root / name).write_text(json.dumps(value, indent=2) + '\n')

def entry(path):
    path = Path(path)
    payload = path.read_bytes()
    return dict(path=path.as_posix(), bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())

source = [entry(path) for path in sorted(Path('src').rglob('*.py'))]
save('source-inventory.json', source)
original = json.loads(Path('p3-evidence/m1b/attempt1/scoped-file-inventory.json').read_text())
scope = [entry(item['path']) for item in original]
scope.append(entry('design/layer-raw.html'))
save('scoped-file-inventory.json', scope)
save('fix-scope-changes.json', [dict(before=old, after=new) for old,new in zip(original,scope) if old['sha256'] != new['sha256']])
baseline = json.loads(Path('p3-evidence/m1a/verification1/source-hashes-after.json').read_text())
baseline = [dict(path=path, sha256=digest) for path,digest in baseline.items()]
current = {item['path']:item['sha256'] for item in source}
changes = [item['path'] for item in baseline if current.get(item['path']) != item['sha256']]
assert not changes, changes
new = sorted(set(current) - {item['path'] for item in baseline})
save('baseline-source-comparison.json', dict(baseline_files=len(baseline),current_files=len(source),changed_existing=changes,new_files=new))
coverage = json.loads((root/'coverage.json').read_text())
touched = {path:coverage['files'][path] for path in new}
assert all(not item['missing_lines'] for item in touched.values())
assert coverage['totals']['percent_covered'] >= 95.84
save('touched-coverage.json', touched)
reports = {}
for name,log in [('full-src','native-full-final'),('native-src','lint'),('native-src-huron','duplication')]:
    paths = re.findall(r'Unified JSON report generated: (.+)$',(root/f'{log}.log').read_text(),re.M)
    assert len(paths) == 1
    payload = Path(paths[0]).read_bytes()
    (root/f'{name}.json').write_bytes(payload)
    report = json.loads(payload)
    reports[name] = duplication_report(report)._asdict()
full = json.loads((root/'full-src.json').read_text())
actual = {Path(item['path']).resolve() for item in source}
scanned = {Path(item['file_path']).resolve() for item in full['system']['dependency_analysis']['module_metrics'].values()}
assert scanned == actual
errors = {key:full[key].get('errors',[]) for key in ('complexity','dead_code','system')}
assert all(value == [] for value in errors.values())
maximum = max(item['metrics']['cognitive_complexity'] for item in full['complexity']['functions'])
assert maximum <= 15
assert full['summary']['dead_code_count'] == full['summary']['high_complexity_count'] == 0
save('native-inventory-validation.json',dict(actual_files=len(actual),scanned_files=len(scanned),missing=[],unexpected=[],errors=errors,max_cognitive_complexity=maximum,reports=reports))
print(json.dumps(dict(source_files=len(source),scope_files=len(scope),new_files=len(new),coverage=coverage['totals'],native=reports),indent=2))
