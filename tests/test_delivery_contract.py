import importlib
import importlib.util

import pytest


def module():
    assert importlib.util.find_spec('delivery_contract') is not None, 'contract implementation missing'
    return importlib.import_module('delivery_contract')


def test_canonical_snapshot_is_order_independent_and_excludes_runtime():
    canonical_snapshot = module().canonical_snapshot
    first = {'text': 'Chào', 'privacy': 'public', 'prepared_at': 'one'}
    second = {'prepared_at': 'two', 'privacy': 'public', 'text': 'Chào'}
    assert canonical_snapshot(first) == canonical_snapshot(second)


def test_snapshot_rejects_non_finite_values_and_secret_fields():
    snapshot = module().canonical_snapshot
    with pytest.raises(ValueError):
        snapshot({'value': float('nan')})
    with pytest.raises(ValueError):
        snapshot({'authorization': 'fake-secret'})


def test_snapshot_rejects_secret_inside_nested_tuple():
    with pytest.raises(ValueError, match='secret'):
        module().canonical_snapshot({'nested': ({'api_key': 'fake'},)})
