import zipfile
from pathlib import Path
from typing import Iterator

class _StreamingZipBuffer:
    """File-like write buffer used by zipfile.ZipFile.

    Intentionally exposes no seek() method so zipfile switches to
    data-descriptor mode and writes the archive in a single forward pass —
    which is what lets us stream the bytes out to the client as they are
    produced.
    """

    def __init__(self) -> None:
        self._pending = bytearray()
        self._pos = 0

    def write(self, data) -> int:
        data = bytes(data)
        self._pending.extend(data)
        self._pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self._pos

    def flush(self) -> None:
        pass

    def drain(self) -> bytes:
        chunk = bytes(self._pending)
        self._pending.clear()
        return chunk


def iter_folder_zip(
    folder: Path,
    arc_root: str,
    chunk_size: int = 65536,
) -> Iterator[bytes]:
    """Yield bytes of a ZIP archive of ``folder`` as it is being built.

    The archive contains ``arc_root`` as its top-level directory, so each
    downloaded archive is self-contained (no parent path required).
    """
    buf = _StreamingZipBuffer()
    with zipfile.ZipFile(
        buf,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=True,
    ) as zf:
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(folder).as_posix()
            arcname = f"{arc_root}/{rel}" if arc_root else rel
            try:
                info = zipfile.ZipInfo.from_file(path, arcname)
            except OSError:
                continue
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as src, zf.open(info, mode="w") as dst:
                while True:
                    data = src.read(chunk_size)
                    if not data:
                        break
                    dst.write(data)
                    chunk = buf.drain()
                    if chunk:
                        yield chunk
            chunk = buf.drain()
            if chunk:
                yield chunk
    final = buf.drain()
    if final:
        yield final


def summarise_folder(folder: Path) -> dict:
    """Cheap stat of ``folder`` — direct file count and total size."""
    file_count = 0
    total_size = 0
    try:
        for entry in folder.rglob("*"):
            if entry.is_file():
                file_count += 1
                try:
                    total_size += entry.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return {"file_count": file_count, "total_size": total_size}
