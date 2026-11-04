import shutil
import subprocess

import pytest
from mutagen.flac import FLAC

from musicmaid import cuesplit, tags as tagio
from musicmaid.library import Library

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")

RATE = 44100


def make_image(path, seconds=(3.0, 2.5, 4.0), fmt=()):
    """One file holding three distinct tones, like a ripped CD image."""
    parts = "".join(f"sine=frequency={300 + 200 * i}:sample_rate={RATE}:duration={s}[a{i}];"
                    for i, s in enumerate(seconds))
    concat = "".join(f"[a{i}]" for i in range(len(seconds))) + f"concat=n={len(seconds)}:v=0:a=1"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-filter_complex", parts + concat, *fmt, str(path)],
                   check=True)
    return path


def frames(sec):
    f = round(sec * 75)
    return f"{f // 75 // 60:02d}:{f // 75 % 60:02d}:{f % 75:02d}"


CUE = """REM GENRE "Ambient"
REM DATE 1999
REM COMMENT "ExactAudioCopy v1.6"
PERFORMER "The Tones"
TITLE "Sine Waves"
FILE "{file}" WAVE
  TRACK 01 AUDIO
    TITLE "Low"
    PERFORMER "The Tones"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Middle: Part/One"
    PERFORMER "Guest Star"
    ISRC GBAYE9900001
    INDEX 00 {gap}
    INDEX 01 {t2}
  TRACK 03 AUDIO
    TITLE "High"
    INDEX 01 {t3}
"""


def write_cue(folder, file="image.flac", name="image.cue", encoding="utf-8"):
    text = CUE.format(file=file, gap=frames(2.9), t2=frames(3.0), t3=frames(5.5))
    p = folder / name
    p.write_bytes(text.encode(encoding))
    return p


def test_parse_and_plan(tmp_path):
    make_image(tmp_path / "image.flac")
    sheet = cuesplit.parse(str(write_cue(tmp_path, file="CDImage.wav")))   # EAC name; the file is .flac now
    assert sheet.files == [str(tmp_path / "image.flac")] and sheet.splittable
    assert (sheet.title, sheet.performer, sheet.date, sheet.genre) == ("Sine Waves", "The Tones", "1999", "Ambient")
    assert [t.start for t in sheet.tracks] == [0, 225, 412]
    jobs = cuesplit.plan(sheet)
    names = [j.dst.rsplit("/", 1)[-1] for j in jobs]
    assert names == ["01 - Low.flac", "02 - Guest Star - Middle - Part-One.flac", "03 - High.flac"]
    # CD frames are 1/75 s = 588 samples: track 3 starts at frame 412 (5.49 s)
    assert [(j.start_sample, j.end_sample) for j in jobs] == [(0, 132300), (132300, 242256), (242256, None)]
    assert jobs[1].tags["artist"] == "Guest Star" and jobs[1].tags["albumartist"] == "The Tones"
    assert jobs[1].tags["isrc"] == "GBAYE9900001" and jobs[2].tags["totaltracks"] == "3"


def test_split_is_sample_exact_and_tagged(tmp_path):
    img = make_image(tmp_path / "image.flac")
    total = FLAC(str(img)).info.total_samples
    sheet = cuesplit.parse(str(write_cue(tmp_path)))
    created, skipped = cuesplit.split(cuesplit.plan(sheet))
    assert len(created) == 3 and not skipped
    lengths = [FLAC(p).info.total_samples for p in created]
    assert lengths == [132300, 109956, total - 242256]          # nothing lost, nothing doubled
    assert sum(lengths) == total
    t = tagio.read(created[1]).tags
    assert t["title"] == "Middle: Part/One" and t["artist"] == "Guest Star" and t["album"] == "Sine Waves"
    assert t["tracknumber"].split("/")[0] == "2" and t["date"] == "1999" and t["genre"] == "Ambient"
    # running again doesn't overwrite
    assert cuesplit.split(cuesplit.plan(sheet))[1] == created


def test_cp1252_cue_and_embedded_sheet(tmp_path):
    img = make_image(tmp_path / "image.flac")
    text = CUE.replace("Sine Waves", "Café Señor").format(file="image.flac", gap=frames(2.9), t2=frames(3.0),
                                                           t3=frames(5.5))
    (tmp_path / "x.cue").write_bytes(text.encode("cp1252"))
    assert cuesplit.parse(str(tmp_path / "x.cue")).title == "Café Señor"
    (tmp_path / "x.cue").unlink()
    f = FLAC(str(img))
    f["CUESHEET"] = text
    f.save()
    sheets = cuesplit.find_sheets([str(tmp_path)], [str(img)])
    assert len(sheets) == 1 and sheets[0].embedded and sheets[0].splittable
    assert sheets[0].title == "Café Señor"


def test_lossy_image_is_cut_without_reencoding(tmp_path):
    make_image(tmp_path / "image.mp3", fmt=("-b:a", "128k"))
    sheet = cuesplit.parse(str(write_cue(tmp_path, file="image.mp3")))
    created, _ = cuesplit.split(cuesplit.plan(sheet))
    assert [p.rsplit(".", 1)[1] for p in created] == ["mp3"] * 3
    import mutagen
    durs = [mutagen.File(p).info.length for p in created]
    assert abs(durs[0] - 3.0) < 0.1 and abs(durs[1] - 2.5) < 0.1


def test_library_split_quarantines_original_and_undo_restores(home, tmp_path):
    music = tmp_path / "music" / "Tones"
    music.mkdir(parents=True)
    make_image(music / "image.flac")
    write_cue(music)
    lib = Library()
    lib.add_folder(str(tmp_path / "music"))
    lib.scan()
    sheets = lib.cue_sheets()
    assert len(sheets) == 1
    made, failed, batch = lib.split_cues(sheets)
    assert (made, failed) == (3, 0)
    names = sorted(t.filename for t in lib.view("all"))
    assert names == ["01 - Low.flac", "02 - Guest Star - Middle - Part-One.flac", "03 - High.flac"]
    assert not (music / "image.flac").exists() and not (music / "image.cue").exists()
    lib.undo(batch)
    assert (music / "image.flac").exists() and (music / "image.cue").exists()
    assert [t.filename for t in lib.view("all")] == ["image.flac"]
    assert sorted(p.name for p in music.iterdir()) == ["image.cue", "image.flac"]


def test_problems_are_reported(tmp_path):
    (tmp_path / "x.cue").write_text('FILE "missing.flac" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n')
    sheet = cuesplit.parse(str(tmp_path / "x.cue"))
    assert not sheet.splittable and "not found" in sheet.problems[0]
    with pytest.raises(cuesplit.CueError):
        cuesplit.plan(sheet)
