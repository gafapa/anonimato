"""Independent coverage policy rejection tests."""
import copy
from tools.check_coverage import failures


def sample():
    summary = dict(num_statements=80, num_branches=20, covered_lines=80, covered_branches=10)
    return {'totals': summary, 'files': {'app\\api.py': {'summary': summary}}}


def test_threshold_includes_branches_and_accepts_windows_paths():
    assert failures(sample(), {'total': 90, 'modules': {'app/api.py': 90}}) == []
    assert failures(sample(), {'total': 90, 'modules': {'app/api.py': 91}}) == ['app/api.py: 90.00% < 91%']


def test_missing_critical_module_cannot_pass_with_high_total():
    assert failures(sample(), {'total': 80, 'modules': {'missing.py': 80}}) == ['missing.py: missing coverage']


def test_reported_percentage_cannot_override_raw_counters():
    report = copy.deepcopy(sample())
    report['totals'].update(covered_lines=0, covered_branches=0, percent_covered=100)
    assert failures(report, {'total': 1, 'modules': {}}) == ['total: 0.00% < 1%']
