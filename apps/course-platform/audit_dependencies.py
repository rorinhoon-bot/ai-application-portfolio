"""Read pinned requirements and installed distribution metadata; never install or download."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from domain import REPO


RUNTIME = {
    'P1': ('01-cited-rag', 'requirements.txt'),
    'P2': ('02-agent-research-workflow', 'requirements.txt'),
    'P3': ('03-mcp-tool-server', 'requirements.lock.txt'),
}
PIN = re.compile(r'^([A-Za-z0-9_.-]+)==([^\s;#]+)')
NORMALIZE = re.compile(r'[-_.]+')
DIRECT_PURPOSE = {
    'fastembed': 'P1 本地向量编码；当前冻结任务只复用分词，不启动向量索引',
    'qdrant-client': 'P1 向量库客户端；当前冻结任务不访问 P1 数据库',
    'fastapi': 'P1 独立 HTTP API；课设工作台不启动该服务',
    'streamlit': 'P1 独立展示；课设工作台使用自身静态前端',
    'langgraph': 'P2 显式状态图与离线研究编排',
    'langgraph-checkpoint-sqlite': 'P2 本机 SQLite checkpoint',
    'mcp': 'P3 stdio MCP 工具协议服务',
}


def canonical(name):
    return NORMALIZE.sub('-', name).lower()


def parse_pins(path):
    pins = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        value = line.strip()
        if not value or value.startswith(('#', '-r ', '--')):
            continue
        match = PIN.match(value)
        if match is None:
            raise ValueError(f'UNPINNED_REQUIREMENT: {path.name}')
        name, version = match.groups()
        key = canonical(name)
        if key in pins:
            raise ValueError(f'DUPLICATE_REQUIREMENT: {key}')
        pins[key] = {'name': name, 'pinned_version': version}
    if not pins:
        raise ValueError(f'EMPTY_REQUIREMENTS: {path.name}')
    return pins


PROBE = r'''
import importlib.metadata as metadata
import json, sys
out = {}
for name in json.load(sys.stdin):
    try:
        dist = metadata.distribution(name)
        info = dist.metadata
        declared = info.get('License-Expression') or info.get('License') or ''
        declared = declared.strip() if len(declared) <= 120 else '[long or unstructured license field]'
        out[name] = {'installed_version': dist.version,
                     'license_declared': declared or None,
                     'license_classifiers': [value for value in info.get_all('Classifier', [])
                                             if value.startswith('License ::')]}
    except metadata.PackageNotFoundError:
        out[name] = {'installed_version': None, 'license_declared': None, 'license_classifiers': []}
print(json.dumps(out))
'''


def inspect_environment(python, names):
    if not python.is_file():
        return None
    environment = {key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH')
                   if key in os.environ}
    environment.update(PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([str(python), '-I', '-B', '-c', PROBE],
                            input=json.dumps(names), text=True, capture_output=True,
                            env=environment, timeout=30)
    if result.returncode:
        raise RuntimeError('METADATA_PROBE_FAILED')
    return json.loads(result.stdout)


def audit(repo=REPO):
    rows = []
    for label, (folder, lock) in RUNTIME.items():
        project = repo / 'projects' / folder
        pins = parse_pins(project / lock)
        installed = inspect_environment(project / '.venv/Scripts/python.exe', list(pins))
        for key, pin in pins.items():
            metadata = installed.get(key) if installed is not None else None
            metadata = metadata or {'installed_version': None, 'license_declared': None,
                                    'license_classifiers': []}
            classifiers = metadata['license_classifiers']
            declared = metadata['license_declared']
            conflict = bool(declared and 'Proprietary License' in ' '.join(classifiers) and
                            ('Apache' in declared or 'MIT' in declared or 'BSD' in declared))
            rows.append({'project': label, 'requirement_file': f'projects/{folder}/{lock}',
                         **pin, 'installed_version': metadata['installed_version'],
                         'version_matches': metadata['installed_version'] == pin['pinned_version'],
                         'license_metadata': declared, 'license_classifiers': classifiers,
                         'license_metadata_conflict': conflict,
                         'license_needs_review': not declared or conflict,
                         'purpose': DIRECT_PURPOSE.get(key, f'{label} 锁文件中的运行依赖或传递依赖'),
                         'offline_alternative': '保留现有环境作离线验证；新机器未获安装许可时暂停该项目功能',
                         'license_verified_with_publisher': False})
    return {'schema_version': 'course-dependency-audit-v1', 'source': 'local locks and installed metadata',
            'installations': 0, 'downloads': 0, 'packages': rows,
            'summary': {'pins': len(rows),
                        'missing_distributions': sum(row['installed_version'] is None for row in rows),
                        'version_mismatches': sum(row['installed_version'] is not None and
                                                  not row['version_matches'] for row in rows),
                        'licenses_needing_review': sum(row['license_needs_review'] for row in rows),
                        'license_metadata_conflicts': sum(row['license_metadata_conflict'] for row in rows)},
            'scope': 'Windows existing virtual environments; not a clean-machine install or license clearance'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
