from pathlib import Path

from playstore_scraper.checkpoint import Checkpoint


def test_checkpoint_roundtrip(tmp_path: Path):
    path = tmp_path / "checkpoint.json"
    cp, resumed = Checkpoint.load_or_create(
        path, app_id="com.foo.bar", config_hash="abc", resume=False
    )
    assert not resumed
    cp.update_stream("en-us-newest-all", token="T1", pages=2, fetched_delta=200, new_delta=180)
    cp.totalUnique = 180
    cp.save()

    cp2, resumed2 = Checkpoint.load_or_create(
        path, app_id="com.foo.bar", config_hash="abc", resume=True
    )
    assert resumed2
    st = cp2.get_stream("en-us-newest-all")
    assert st.token == "T1"
    assert st.pages == 2
    assert st.fetched == 200
    assert st.new == 180
    assert cp2.totalUnique == 180


def test_mark_done(tmp_path: Path):
    path = tmp_path / "checkpoint.json"
    cp, _ = Checkpoint.load_or_create(
        path, app_id="com.foo.bar", config_hash="abc", resume=False
    )
    cp.mark_done("en-us-newest-all", "exhausted")
    cp.save()
    st = cp.get_stream("en-us-newest-all")
    assert st.done is True
    assert st.doneReason == "exhausted"
    assert st.token is None
