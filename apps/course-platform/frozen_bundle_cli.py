"""Verify a frozen-delivery ZIP without extraction, network, or application DB."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

from domain import INTEGRATION, safe_path
sys.path.insert(0,str(INTEGRATION))
from common import P2
sys.path.insert(0,str(P2 / 'src'))
from frozen_bundle import verify_content


def verified_content(zip_file):
    path=safe_path(Path(zip_file))
    if path.stat().st_size>2*1024*1024:
        raise ValueError('BUNDLE_TOO_LARGE')
    raw=path.read_bytes()
    if len(raw)>2*1024*1024:
        raise ValueError('BUNDLE_TOO_LARGE')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos=archive.infolist()
        if not 1<=len(infos)<=300 or len({info.filename for info in infos})!=len(infos) or\
                any(info.is_dir() or info.file_size>2*1024*1024 or info.compress_size>2*1024*1024 or
                    info.flag_bits & 1 for info in infos) or sum(i.file_size for i in infos)>2*1024*1024:
            raise ValueError('BUNDLE_INVALID')
        content={i.filename:archive.read(i) for i in infos}
    result=verify_content(content)
    return content, hashlib.sha256(raw).hexdigest(), result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip_file',type=Path)
    args=parser.parse_args()
    _, _, result=verified_content(args.zip_file)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    try:
        main()
    except Exception:
        print('{"bundle_consistent":false,"error":"BUNDLE_INVALID"}')
        raise SystemExit(2)
