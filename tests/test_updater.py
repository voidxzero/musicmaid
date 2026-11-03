import hashlib
import io
import sys
import tarfile

import pytest

from musicmaid import updater


class FakeResp:
    def __init__(self, status=200, json_data=None, content=b""):
        self.status_code, self._json, self.content = status, json_data, content
        self.headers = {"Content-Length": str(len(content))}

    def json(self):
        return self._json

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def release(version, assets):
    return {"tag_name": f"v{version}", "body": "Notes", "html_url": "https://github.com/x/releases/tag/v" + version,
            "draft": False, "prerelease": False,
            "assets": [{"name": n, "browser_download_url": f"https://dl/{n}", "size": len(data),
                        "digest": "sha256:" + hashlib.sha256(data).hexdigest()} for n, data in assets.items()]}


@pytest.fixture
def fake_net(monkeypatch):
    routes = {}

    class Session:
        def get(self, url, **kw):
            return routes[url]
    import musicmaid.net as net
    monkeypatch.setattr(net, "session", lambda: Session())
    return routes


def test_version_compare():
    assert updater.is_newer("0.2.0", "0.1.0")
    assert updater.is_newer("v0.1.1", "0.1")
    assert updater.is_newer("1.0", "0.9.9")
    assert not updater.is_newer("0.1.0", "0.1.0")
    assert not updater.is_newer("0.1", "0.1.0")
    assert not updater.is_newer("garbage", "0.1.0")


@pytest.mark.parametrize("kind,expected", [
    ("windows-installer", "MusicMaid-9.0.0-setup.exe"),
    ("windows-portable", "MusicMaid-9.0.0-windows-x64.zip"),
    ("appimage", "MusicMaid-9.0.0-x86_64.AppImage"),
    ("linux-tarball", "MusicMaid-9.0.0-linux-x86_64.tar.gz"),
])
def test_check_picks_asset_for_install_kind(fake_net, monkeypatch, kind, expected):
    monkeypatch.setattr(updater, "_arch", lambda: "x86_64")
    monkeypatch.setattr(sys, "executable", "/opt/MusicMaid/MusicMaid")
    names = ["MusicMaid-9.0.0-setup.exe", "MusicMaid-9.0.0-windows-x64.zip", "MusicMaid-9.0.0-x86_64.AppImage",
             "MusicMaid-9.0.0-linux-x86_64.tar.gz"]
    fake_net[updater.LATEST_API] = FakeResp(json_data=release("9.0.0", {n: n.encode() for n in names}))
    upd = updater.check(kind=kind)
    assert upd.version == "9.0.0" and upd.asset_name == expected and upd.can_install
    assert upd.sha256 == hashlib.sha256(expected.encode()).hexdigest()


def test_check_up_to_date_and_source(fake_net):
    fake_net[updater.LATEST_API] = FakeResp(json_data=release(updater.__version__, {}))
    assert updater.check(kind="source") is None
    fake_net[updater.LATEST_API] = FakeResp(json_data=release("99.0", {"MusicMaid-99.0-setup.exe": b"x"}))
    upd = updater.check(kind="source")
    assert upd.version == "99.0" and not upd.can_install
    fake_net[updater.LATEST_API] = FakeResp(status=404)
    assert updater.check() is None
    fake_net[updater.LATEST_API] = FakeResp(status=500)
    with pytest.raises(updater.UpdateError):
        updater.check()


def test_download_rejects_bad_checksum(fake_net, tmp_path):
    upd = updater.Update("9.0", "", "", "appimage", "a.AppImage", "https://dl/a", hashlib.sha256(b"good").hexdigest())
    fake_net["https://dl/a"] = FakeResp(content=b"evil")
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(upd, tmp_path)
    assert not (tmp_path / "a.AppImage").exists()
    fake_net["https://dl/a"] = FakeResp(content=b"good")
    assert updater.download(upd, tmp_path).read_bytes() == b"good"
    upd.sha256 = ""
    with pytest.raises(updater.UpdateError):
        updater.download(upd, tmp_path)


def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_linux_tarball_update_swaps_folder(fake_net, monkeypatch, tmp_path):
    app = tmp_path / "apps" / "MusicMaid"
    (app / "_internal").mkdir(parents=True)
    (app / "MusicMaid").write_bytes(b"old")
    (app / "_internal" / "stale.so").write_bytes(b"old")
    monkeypatch.setattr(sys, "executable", str(app / "MusicMaid"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert updater.install_kind() == "linux-tarball"
    data = _tarball({"MusicMaid/MusicMaid": b"new", "MusicMaid/_internal/lib.so": b"new"})
    upd = updater.Update("9.0", "", "", "linux-tarball", "MusicMaid-9.0-linux-x86_64.tar.gz", "https://dl/t",
                         hashlib.sha256(data).hexdigest())
    fake_net["https://dl/t"] = FakeResp(content=data)

    updater.install(upd, relaunch=False)

    assert (app / "MusicMaid").read_bytes() == b"new"
    assert not (app / "_internal" / "stale.so").exists()
    assert sorted(p.name for p in app.parent.iterdir()) == [".MusicMaid.old", "MusicMaid"]
    updater.cleanup_previous()
    assert [p.name for p in app.parent.iterdir()] == ["MusicMaid"]


def test_bad_archive_leaves_install_alone(fake_net, monkeypatch, tmp_path):
    app = tmp_path / "MusicMaid"
    app.mkdir()
    (app / "MusicMaid").write_bytes(b"old")
    monkeypatch.setattr(sys, "executable", str(app / "MusicMaid"))
    data = _tarball({"other/thing": b"x"})
    upd = updater.Update("9.0", "", "", "linux-tarball", "x.tar.gz", "https://dl/t", hashlib.sha256(data).hexdigest())
    fake_net["https://dl/t"] = FakeResp(content=data)
    with pytest.raises(updater.UpdateError):
        updater.install(upd, relaunch=False)
    assert (app / "MusicMaid").read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["MusicMaid"]


def test_appimage_update_replaces_file(fake_net, monkeypatch, tmp_path):
    image = tmp_path / "MusicMaid-0.1.0-x86_64.AppImage"
    image.write_bytes(b"old")
    monkeypatch.setenv("APPIMAGE", str(image))
    upd = updater.Update("9.0", "", "", "appimage", "MusicMaid-9.0-x86_64.AppImage", "https://dl/a",
                         hashlib.sha256(b"new").hexdigest())
    fake_net["https://dl/a"] = FakeResp(content=b"new")
    updater.install(upd, relaunch=False)
    assert image.read_bytes() == b"new" and image.stat().st_mode & 0o111
    assert [p.name for p in tmp_path.iterdir()] == [image.name]


def test_windows_script(tmp_path):
    s = updater.windows_script(4242, tmp_path / "new" / "MusicMaid", tmp_path / "app", "MusicMaid.exe", tmp_path, True)
    assert 'PID eq 4242' in s and "robocopy" in s and 'start ""' in s and "MusicMaid.exe" in s


def test_clean_env_strips_bundle_vars(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "/bundle")
    monkeypatch.setenv("APPIMAGE", "/x.AppImage")
    env = updater.clean_env()
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "_PYI_APPLICATION_HOME_DIR" not in env and "APPIMAGE" not in env
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
