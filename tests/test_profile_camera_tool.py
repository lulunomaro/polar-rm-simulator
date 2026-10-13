from types import SimpleNamespace

import pytest

from tools.profile_camera import compare, distribution


def test_empty_distribution_never_claims_freshness():
    result = distribution([])
    assert result['count'] == 0
    assert result['within_80ms_fraction'] is None
    assert all(result[k] is None for k in ('p50_ms','p95_ms','p99_ms','max_ms'))


def test_freshness_includes_boundary_and_retains_late_samples():
    result = distribution([.010, .080, .081, .200])
    assert result['count'] == 4
    assert result['within_80ms_count'] == 2
    assert result['within_80ms_fraction'] == .5
    assert result['max_ms'] == pytest.approx(200)
    assert result['p50_ms'] == pytest.approx(80.5)


def test_existing_evidence_directory_is_never_overwritten(tmp_path):
    evidence = tmp_path / 'evidence'; evidence.mkdir()
    marker = evidence / 'failed.log'; marker.write_text('original failure', encoding='utf-8')
    with pytest.raises(FileExistsError):
        compare(SimpleNamespace(out=evidence, seconds=10., warmup=2., order='baseline,current'))
    assert marker.read_text(encoding='utf-8') == 'original failure'
    assert list(evidence.iterdir()) == [marker]
