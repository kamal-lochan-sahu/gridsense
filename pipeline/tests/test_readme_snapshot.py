import pytest

from pipeline import readme_snapshot as snap


def forecast(**countries):
    return {
        "countries": {
            name: {
                "track_record": {
                    "summary": {"7d": week},
                    "daily": [{"date": "2026-11-03"}, {"date": last}],
                }
            }
            for name, (week, last) in countries.items()
        }
    }


FULL = forecast(
    germany=({"gridsense": 2.58, "tso": 2.98, "naive": 3.49}, "2026-11-04"),
    france=({"gridsense": 3.09, "tso": 1.61, "naive": 3.29}, "2026-11-04"),
)


def test_table_marks_the_lowest_error_per_country():
    block = snap.render(FULL)
    assert "| Germany | **2.58 %** | 2.98 % | 3.49 % |" in block
    assert "| France | 3.09 % | **1.61 %** | 3.29 % |" in block
    assert "7 days to 4 November 2026" in block


def test_date_is_the_oldest_last_day_and_missing_values_are_marked():
    data = forecast(
        germany=({"gridsense": 2.0, "tso": None, "naive": 3.0}, "2026-11-04"),
        spain=({"gridsense": 2.0, "tso": 1.0, "naive": 3.0}, "2026-11-02"),
    )
    block = snap.render(data)
    assert "7 days to 2 November 2026" in block
    assert "| Germany | **2.00 %** | n/a | 3.00 % |" in block


def test_countries_without_a_track_record_are_skipped_and_none_at_all_fails():
    data = forecast(germany=({"gridsense": 2.0, "tso": 1.0, "naive": 3.0}, "2026-11-04"))
    data["countries"]["poland"] = {"track_record": {}}
    block = snap.render(data)
    assert "Germany" in block and "Poland" not in block
    with pytest.raises(snap.SnapshotError):
        snap.render({"countries": {"poland": {}}})


def test_update_replaces_only_the_marked_part_and_is_idempotent():
    readme = f"intro\n\n{snap.START}\nold numbers\n{snap.END}\n\noutro\n"
    block = snap.render(FULL)
    once = snap.update_readme(readme, block)
    assert once.startswith("intro\n\n") and once.endswith("\n\noutro\n")
    assert "old numbers" not in once and block in once
    assert snap.update_readme(once, block) == once


def test_update_without_markers_fails():
    with pytest.raises(snap.SnapshotError, match="markers"):
        snap.update_readme("no markers here", "x")


def test_main_updates_a_readme_from_a_local_file(tmp_path, capsys):
    import json

    source = tmp_path / "forecast.json"
    source.write_text(json.dumps(FULL), encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(f"a\n{snap.START}\nold\n{snap.END}\nb\n", encoding="utf-8")
    assert snap.main(["--file", str(source), "--readme", str(readme)]) == 0
    assert "**2.58 %**" in readme.read_text(encoding="utf-8")
    broken = tmp_path / "broken.json"
    broken.write_text("{}", encoding="utf-8")
    assert snap.main(["--file", str(broken), "--readme", str(readme)]) == 1
    assert "snapshot not updated" in capsys.readouterr().err
