"""Inspect owned disposable fixture cleanup and stop the temporary Linux VM."""
import json
import pathlib
import subprocess
import time

root = pathlib.Path('p3-evidence/m1b/fix1')
results = []
with (root/'cleanup.log').open('w') as output:
    def run(command):
        output.write('$ ' + repr(command) + '\n')
        output.flush()
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT)
        results.append(dict(command=command, exit=result.returncode))
        return result.returncode
    try:
        assert run(['podman','machine','start']) == 0
        for attempt in range(60):
            if subprocess.run(['podman','info'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('VM did not become ready for cleanup inspection')
        program = 'import glob,json; state={"controlled_roots":glob.glob("/var/lib/huron-controlled-test-*"),"controller_sockets":glob.glob("/run/huron-controller-test-*")}; print(json.dumps(state)); assert not any(state.values())'
        import shlex
        assert run(['podman','machine','ssh','sudo python3 -c ' + shlex.quote(program)]) == 0
        assert run(['podman','ps','-a']) == 0
    finally:
        run(['podman','machine','stop'])
        (root/'cleanup-results.json').write_text(json.dumps(results,indent=2))
