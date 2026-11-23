import argparse
from pathlib import Path
from app.db import SessionLocal, settings
from app.datasets import export_dataset

def main():
    parser = argparse.ArgumentParser(description='Export labels with cow-level leakage protection')
    parser.add_argument('--output', type=Path, default=settings.storage_root / 'exports' / 'training.csv')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--train', type=float, default=0.8)
    parser.add_argument('--validation', type=float, default=0.1)
    parser.add_argument('--include-unapproved', action='store_true', help='Explicitly include pending and rejected labels; unsuitable for normal training')
    args = parser.parse_args()
    with SessionLocal() as session:
        print(export_dataset(session, args.output, args.seed, args.train, args.validation, not args.include_unapproved))

if __name__ == '__main__':
    main()
