"""Reject missing coverage and regressions in each critical Python module."""
import argparse
import json
from pathlib import Path


def failures(report, policy):
    files = {name.replace('\\', '/'): value for name, value in report['files'].items()}
    results = []
    checks = [('total', report['totals'], policy['total'])]
    for name, minimum in policy['modules'].items():
        if name not in files:
            results.append(f'{name}: missing coverage')
        else:
            checks.append((name, files[name]['summary'], minimum))
    for name, summary, minimum in checks:
        total = summary['num_statements'] + summary['num_branches']
        covered = summary['covered_lines'] + summary['covered_branches']
        percent = 100 * covered / total if total else 0
        if percent + 1e-9 < minimum:
            results.append(f'{name}: {percent:.2f}% < {minimum}%')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--policy', type=Path, default=Path(__file__).resolve().parents[1] / 'packaging/coverage-policy.json')
    args = parser.parse_args()
    errors = failures(json.loads(args.report.read_text('utf-8')), json.loads(args.policy.read_text('utf-8')))
    for error in errors:
        print(error)
    if errors:
        raise SystemExit(1)
    print('All critical module coverage thresholds passed')


if __name__ == '__main__':
    main()
