import argparse
from pathlib import Path
from app.db import SessionLocal
from app.datasets import RESOURCES, import_csv

def main():
    parser = argparse.ArgumentParser(description='Atomic, repeatable CSV metadata import')
    parser.add_argument('resource', choices=RESOURCES)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    with SessionLocal() as session:
        print(import_csv(session, args.resource, args.file))

if __name__ == '__main__':
    main()
