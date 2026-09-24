"""Read models from ZIP bundles and replace one model without changing its path."""
from __future__ import annotations

import copy
import io
import shutil
import zlib
from contextlib import contextmanager
from zipfile import BadZipFile, ZipFile


class ArchiveError(ValueError):
    pass


@contextmanager
def _open_archive(data: bytes):
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            yield archive
    except (BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error) as exc:
        raise ArchiveError(f"Cannot read or rebuild this ZIP: {exc}") from exc


def _model_entry(archive: ZipFile, path: str):
    matches = [entry for entry in archive.infolist() if entry.filename == path]
    if len(matches) != 1 or matches[0].is_dir() or not path.lower().endswith(".glb"):
        raise ArchiveError("Choose a GLB with a unique path in the ZIP.")
    return matches[0]


def list_glbs(zip_data: bytes) -> list[str]:
    """Return full GLB paths in archive order, rejecting ambiguous model paths."""
    with _open_archive(zip_data) as archive:
        paths = [entry.filename for entry in archive.infolist()
                 if not entry.is_dir() and entry.filename.lower().endswith(".glb")]
        if not paths:
            raise ArchiveError("This ZIP does not contain any GLB files.")
        if len(paths) != len(set(paths)):
            raise ArchiveError("This ZIP contains duplicate GLB paths. Give each model a unique path first.")
        return paths


def read_glb_from_zip(zip_data: bytes, path: str) -> bytes:
    with _open_archive(zip_data) as archive:
        return archive.read(_model_entry(archive, path))


def replace_glb_in_zip(zip_data: bytes, path: str, processed_glb: bytes) -> bytes:
    """Build a new ZIP, replacing exactly one GLB and retaining other contents.

    Paths, entry order, timestamps, permissions, compression methods and comments
    are retained. Files are never extracted to disk and the input is untouched.
    """
    output = io.BytesIO()
    with _open_archive(zip_data) as source:
        target = _model_entry(source, path)
        with ZipFile(output, "w") as destination:
            destination.comment = source.comment
            for entry in source.infolist():
                metadata = copy.copy(entry)
                if entry is target:
                    destination.writestr(metadata, processed_glb)
                else:
                    with source.open(entry) as reader, destination.open(metadata, "w") as writer:
                        shutil.copyfileobj(reader, writer)
    return output.getvalue()
