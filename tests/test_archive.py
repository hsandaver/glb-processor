import io
import warnings
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from archive import ArchiveError, list_glbs, read_glb_from_zip, replace_glb_in_zip
from processor import convert_glb, parse_glb
from test_processor import fixture_glb


def make_zip(entries):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.comment = b"Original bundle"
        for path, data in entries:
            info = ZipInfo(path, date_time=(2024, 3, 2, 12, 30, 0))
            info.comment = b"Entry comment"
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_STORED if path.endswith("/") else ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def test_processed_model_replaces_only_selected_entry_and_preserves_metadata():
    original_model = fixture_glb()
    source = make_zip([
        ("bundle/", b""),
        ("bundle/models/object.GLB", original_model),
        ("another/object.glb", original_model),
        ("bundle/manifest.json", b'{"model": "models/object.GLB"}'),
        ("bundle/annotations.json", b'{"annotations": []}'),
        ("bundle/textures/café.png", b"unrelated image"),
    ])
    assert list_glbs(source) == ["bundle/models/object.GLB", "another/object.glb"]
    selected = read_glb_from_zip(source, "bundle/models/object.GLB")
    processed, _ = convert_glb(selected)
    output = replace_glb_in_zip(source, "bundle/models/object.GLB", processed)
    with ZipFile(io.BytesIO(source)) as before, ZipFile(io.BytesIO(output)) as after:
        assert after.testzip() is None
        assert after.namelist() == before.namelist()
        assert after.comment == before.comment
        for old, new in zip(before.infolist(), after.infolist()):
            for field in ("date_time", "comment", "external_attr", "compress_type", "extra"):
                assert getattr(new, field) == getattr(old, field)
            expected = processed if old.filename == "bundle/models/object.GLB" else before.read(old)
            assert after.read(new) == expected
        assert before.read("bundle/models/object.GLB") == original_model
    model, _ = parse_glb(read_glb_from_zip(output, "bundle/models/object.GLB"))
    assert model["materials"][0]["extensions"] == {"KHR_materials_unlit": {}}


def test_duplicate_non_model_entries_are_preserved_individually():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        source = make_zip([("model.glb", b"old"), ("notes.txt", b"first"), ("notes.txt", b"second")])
        output = replace_glb_in_zip(source, "model.glb", b"new")
    with ZipFile(io.BytesIO(output)) as archive:
        assert [archive.read(entry) for entry in archive.infolist()] == [b"new", b"first", b"second"]


def test_duplicate_glb_paths_are_rejected():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        source = make_zip([("model.glb", b"one"), ("model.glb", b"two")])
    with pytest.raises(ArchiveError, match="duplicate"):
        list_glbs(source)
    with pytest.raises(ArchiveError, match="unique"):
        replace_glb_in_zip(source, "model.glb", b"new")


@pytest.mark.parametrize("source", [b"not a zip", b"PK\x03\x04truncated"])
def test_invalid_zip_has_useful_error(source):
    for action in (lambda: list_glbs(source),
                   lambda: read_glb_from_zip(source, "model.glb"),
                   lambda: replace_glb_in_zip(source, "model.glb", b"new")):
        with pytest.raises(ArchiveError, match="Cannot read or rebuild"):
            action()


def test_missing_models_and_invalid_target_are_rejected():
    source = make_zip([("notes.txt", b"notes"), ("empty.glb/", b"")])
    with pytest.raises(ArchiveError, match="does not contain"):
        list_glbs(source)
    for path in ("missing.glb", "notes.txt", "empty.glb/"):
        with pytest.raises(ArchiveError, match="unique path"):
            replace_glb_in_zip(source, path, b"new")


def test_corrupt_other_file_prevents_zip_download():
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        archive.writestr("model.glb", b"old model")
        archive.writestr("notes.txt", b"unique contents")
    damaged = buffer.getvalue().replace(b"unique contents", b"broken contents")
    with pytest.raises(ArchiveError, match="CRC"):
        replace_glb_in_zip(damaged, "model.glb", b"new model")
