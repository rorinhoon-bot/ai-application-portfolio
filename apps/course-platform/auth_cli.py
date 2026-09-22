"""Create local identity-workspace users without putting passwords in commands or files."""
import argparse
from getpass import getpass
import json
import sys

from domain import APP, AppError, require
from service import Service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', default=str(APP / '.runtime' / 'graduation-g3-state'))
    parser.add_argument('--username', required=True)
    parser.add_argument('--role', choices=('admin', 'researcher', 'reviewer'), required=True)
    args = parser.parse_args()
    password = getpass('新账户密码（至少12字符）：')
    require(password == getpass('再次输入密码：'), 'INPUT_INVALID')
    service = Service(args.state_dir, auth_required=True)
    try:
        print(json.dumps(service.auth.create_user(args.username, password, args.role), ensure_ascii=False))
    finally:
        service.close()


if __name__ == '__main__':
    try:
        main()
    except (AppError, OSError) as error:
        print(json.dumps({'error': error.code if isinstance(error, AppError) else 'STARTUP_FAILED'}, ensure_ascii=False))
        sys.exit(1)
