import sys

if "--self-test" in sys.argv:
    # Smoke test of a frozen build: python modules, HTTPS certificates, tag IO and fpcalc.
    # The GUI build has no console on Windows, so results also go to a file.
    import os
    import tempfile
    import traceback

    out = []
    ok = True
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401
        from musicmaid import __version__, net, tags
        from musicmaid.fingerprint import find_fpcalc
        out.append(f"MusicMaid {__version__}")
        data = net.get_json("https://musicbrainz.org/ws/2/artist/a74b1b7f-71a5-4011-9441-d0b5e4122711",
                            params={"fmt": "json"})
        out.append(f"HTTPS/MusicBrainz: {data['name']}")
        out.append(f"fpcalc: {find_fpcalc() or 'NOT FOUND'}")
        out.append(f"tag formats: {len(tags.AUDIO_EXTENSIONS)}")
        from musicmaid.gui import skins
        bundled = sorted(skins.bundled_skin_dir().glob("*.json"))
        out.append(f"skins: {len(skins.theme_names())} ({len(bundled)} from files)")
        if not bundled or skins.skin_errors:
            raise RuntimeError(f"skin files missing or broken: {skins.skin_errors}")
        app = QApplication.instance() or QApplication([])
        for name in skins.theme_names():
            skins.apply(name)
    except Exception:
        ok = False
        out.append(traceback.format_exc())
    out.append("SELF-TEST " + ("OK" if ok else "FAILED"))
    text = "\n".join(out)
    print(text)
    with open(os.path.join(tempfile.gettempdir(), "musicmaid-selftest.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    sys.exit(0 if ok else 1)

from musicmaid.gui.mainwindow import main  # noqa: E402

sys.exit(main())
