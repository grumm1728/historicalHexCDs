import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import validate_metro_counts as v


def test_ninety_percent_boundary_and_each_congress_independent():
    rows = [dict(congress=c, within_one=i < (44 if c == 119 else 45))
            for c in v.CONGRESSES for i in range(50)]
    results = v.summary(rows)
    assert all(ok for _, _, _, ok in results[:-1])
    assert results[-1] == (119, 44, 50, False)


@pytest.mark.parametrize("mutation", ["missing", "string", "duplicate", "congress"])
def test_rejects_invalid_labels_and_duplicate_districts(tmp_path, mutation):
    p = dict(state_fips="48", cd_index=1, congress_number=119, is_metro=True)
    if mutation == "missing":
        del p["is_metro"]
    elif mutation == "string":
        p["is_metro"] = "false"
    elif mutation == "congress":
        p["congress_number"] = 118
    features = [dict(properties=p)] * (2 if mutation == "duplicate" else 1)
    path = tmp_path / "119.geojson"
    path.write_text(json.dumps(dict(features=features)), encoding="utf-8")
    with pytest.raises(ValueError):
        v.exported_counts(path, 119)


def test_counts_actual_labels_including_zero_metro_states(tmp_path):
    features = [dict(properties=dict(state_fips=f, cd_index=i, congress_number=119, is_metro=m))
                for f, i, m in [("48", 1, True), ("48", 2, False), ("02", 1, False)]]
    path = tmp_path / "119.geojson"
    path.write_text(json.dumps(dict(features=features)), encoding="utf-8")
    assert v.exported_counts(path, 119) == {"48": (2, 1), "02": (1, 0)}


def test_rejects_incomplete_benchmark(tmp_path):
    with pytest.raises(ValueError, match="unique state/Congress"):
        v.compare([], tmp_path)
    rows = [dict(congress=c, state_fips="48", seats=38) for c in v.CONGRESSES]
    with pytest.raises(ValueError, match="50 states"):
        v.compare(rows, tmp_path)
