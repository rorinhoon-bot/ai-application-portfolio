"""Verify a frozen-delivery ZIP without extraction, network, or application DB."""
import argparse
import json
from pathlib import Path
import sys
import zipfile

from domain import INTEGRATION, safe_path
sys.path.insert(0,str(INTEGRATION))
from frozen_bundle import verify_content


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip_file',type=Path)
    args=parser.parse_args()
    path=safe_path(args.zip_file)
    if path.stat().st_size>2*1024*1024:
        raise ValueError('BUNDLE_TOO_LARGE')
    with zipfile.ZipFile(path) as archive:
        infos=archive.infolist()
        if not 1<=len(infos)<=300 or len({info.filename for info in infos})!=len(infos) or\
                any(info.is_dir() or info.file_size>2*1024*1024 or info.compress_size>2*1024*1024 or
                    info.flag_bits & 1 for info in infos) or sum(i.file_size for i in infos)>2*1024*1024:
            raise ValueError('BUNDLE_INVALID')
        content={i.filename:archive.read(i) for i in infos}
    print(json.dumps(verify_content(content),ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    try:
        main()
    except Exception:
        print('{"bundle_consistent":false,"error":"BUNDLE_INVALID"}')
        raise SystemExit(2)
