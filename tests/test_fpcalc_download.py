import hashlib
import io
import sys
import zipfile

import pytest

from musicmaid import fingerprint as fp


def _fake_archive(platform_key):
    """A small archive laid out like the official Chromaprint release, and its checksum."""
    suffix, _ = fp._DOWNLOADS[platform_key]
    exe = "fpcalc.exe" if platform_key[0] == "win32" else "fpcalc"
    body = b"#!/bin/sh\necho fake fpcalc\n"
    buf = io.BytesIO()
    folder = f"chromaprint-fpcalc-{fp.CHROMAPRINT_VERSION}-{suffix.split('.')[0]}"
    if suffix.endswith(".zip"):
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(f"{folder}/{exe}", body)
    else:
        import tarfile
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            info = tarfile.TarInfo(f"{folder}/{exe}")
            info.size = len(body)
            t.addfile(info, io.BytesIO(body))
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest(), body


@pytest.mark.parametrize("key", [("linux", "x86_64"), ("win32", "x86_64")])
def test_download_installs_into_data_dir(home, monkeypatch, key):
    data, digest, body = _fake_archive(key)
    monkeypatch.setattr(fp, "_download_key", lambda: key)
    monkeypatch.setattr(fp, "_EXE", "fpcalc.exe" if key[0] == "win32" else "fpcalc")
    monkeypatch.setitem(fp._DOWNLOADS, key, (fp._DOWNLOADS[key][0], digest))
    import musicmaid.net as net
    seen = []
    monkeypatch.setattr(net, "get_bytes", lambda url, **kw: seen.append(url) or data)

    path = fp.download_fpcalc()

    assert seen[0].startswith("https://github.com/acoustid/chromaprint/releases/download/v")
    assert path == str(fp.downloaded_fpcalc_path())
    assert fp.downloaded_fpcalc_path().read_bytes() == body
    assert str(home) in path


def test_checksum_mismatch_is_rejected(home, monkeypatch):
    key = ("linux", "x86_64")
    data, _, _ = _fake_archive(key)
    monkeypatch.setattr(fp, "_download_key", lambda: key)
    import musicmaid.net as net
    monkeypatch.setattr(net, "get_bytes", lambda url, **kw: data)  # real pinned hash won't match
    with pytest.raises(fp.FingerprintError, match="checksum"):
        fp.download_fpcalc()
    assert not fp.downloaded_fpcalc_path().exists()


def test_find_fpcalc_uses_downloaded_copy(home, monkeypatch):
    monkeypatch.setattr(fp.shutil, "which", lambda exe: None)
    monkeypatch.setattr(fp, "__file__", str(home / "nowhere" / "pkg" / "fingerprint.py"))
    monkeypatch.setattr(sys, "executable", str(home / "nowhere" / "python"))
    assert fp.find_fpcalc() is None
    target = fp.downloaded_fpcalc_path()
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    assert fp.find_fpcalc() == str(target)


def test_pinned_hashes_match_real_releases():
    # sizes/hashes verified against github.com/acoustid/chromaprint v1.5.1 assets
    assert set(fp._DOWNLOADS) == {("win32", "x86_64"), ("linux", "x86_64")}
    assert all(len(h) == 64 for _, h in fp._DOWNLOADS.values())
