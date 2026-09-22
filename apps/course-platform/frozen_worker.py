"""P2 interpreter entry point for frozen-project jobs; no external provider path."""
import argparse
import base64
import io
import json
from pathlib import Path
import re
import sys
import zipfile

from domain import INTEGRATION, decode, fields, require, safe_path

sys.path.insert(0, str(INTEGRATION))
from cli import summary
from frozen_runtime import FrozenRuntime, initialize, validate_snapshot, LIMITATIONS
from frozen_bundle import build_content, verify_content
from workflow_runtime import read_json


def view(runtime):
    state = summary(runtime.state())
    state['approvals'] = [read_json(p) for p in sorted((runtime.root / 'approvals').glob('*.json'))]
    state['tool_events'] = [read_json(p) for p in sorted((runtime.root / 'tool-events').glob('*.json'))]
    state['human_revision_count'] = len(runtime.revisions())
    state['limitations'] = LIMITATIONS
    return {'state': state}


def handle(root, message):
    fields(message, 'operation snapshot request_id payload')
    operation, snapshot, payload = message['operation'], message['snapshot'], message['payload']
    require(operation in ('create','approve','reject','cancel','recover','revise','export') and
            type(payload) is dict and re.fullmatch('[a-f0-9]{32}', message['request_id']) is not None)
    validate_snapshot(snapshot)
    root = safe_path(root, directory=True)
    run = root / ('run-' + root.name.removeprefix('task-'))
    require(re.fullmatch('run-[a-f0-9]{32}', run.name) is not None)
    existing = [p for p in root.iterdir() if p.name.startswith('run-')]
    require(not existing or len(existing) == 1 and existing[0] == run, 'ENGINE_FAILED')
    if operation == 'create' and not (run / 'run.json').exists():
        initialize(run, snapshot)
    elif operation == 'recover' and not (run / 'run.json').exists():
        initialize(run, snapshot)
    require((run / 'run.json').exists(), 'ENGINE_FAILED')
    with FrozenRuntime(run, snapshot) as runtime:
        if operation in ('create','recover'):
            runtime.start()
            if operation == 'recover':
                runtime.recover()
        elif operation in ('approve','reject','cancel'):
            fields(payload, 'expected_hash note')
            runtime.decide(operation, payload['expected_hash'], actor='operator-cli')
        elif operation == 'revise':
            fields(payload, 'expected_hash summary limitations note')
            runtime.revise(message['request_id'], payload)
        else:
            content = build_content(runtime)
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in sorted(content.items()):
                    info = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info,data)
            return {'zip_base64':base64.b64encode(stream.getvalue()).decode(),
                    'verification':verify_content(content)}
        return view(runtime)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(393217)
        require(len(raw) <= 393216)
        print(json.dumps(handle(args.task_root,decode(raw)),ensure_ascii=False))
    except Exception:
        print('{"error":{"code":"ENGINE_FAILED"}}')
        raise SystemExit(2)
