"""Matching logic with canned AcoustID / MusicBrainz data (no network)."""
from musicmaid.config import Settings
from musicmaid.db import Track
from musicmaid.identify import Identifier, candidates_from_acoustid, confidence, query_tags
from musicmaid.providers import musicbrainz as mb

ACOUSTID = [{
    "id": "acid-1", "score": 0.97,
    "recordings": [{
        "id": "rec-1", "title": "Airbag", "duration": 284,
        "artists": [{"id": "art-1", "name": "Radiohead"}],
        "releasegroups": [
            {"id": "rg-comp", "type": "Album", "secondarytypes": ["Compilation"], "title": "Now 97",
             "releases": [{"id": "rel-comp", "country": "GB", "date": {"year": 1997},
                           "mediums": [{"position": 1, "track_count": 40, "tracks": [{"position": 12}]}]}]},
            {"id": "rg-okc", "type": "Album", "title": "OK Computer",
             "releases": [
                 {"id": "rel-reissue", "country": "XE", "date": {"year": 2009, "month": 3},
                  "mediums": [{"position": 1, "track_count": 12, "tracks": [{"position": 1}]}]},
                 {"id": "rel-okc", "country": "GB", "date": {"year": 1997, "month": 6, "day": 16},
                  "mediums": [{"position": 1, "track_count": 12, "tracks": [{"position": 1}]}]}]},
        ],
    }],
}]

RELEASE = {
    "id": "rel-okc", "title": "OK Computer", "status": "Official", "country": "GB", "date": "1997-06-16",
    "artist-credit": [{"name": "Radiohead", "artist": {"id": "art-1", "name": "Radiohead"}}],
    "release-group": {"id": "rg-okc", "primary-type": "Album", "first-release-date": "1997-05-21"},
    "label-info": [{"catalog-number": "NODATA 02", "label": {"name": "Parlophone"}}],
    "genres": [{"name": "alternative rock", "count": 9}],
    "media": [{"position": 1, "track-count": 12, "tracks": [{
        "id": "trk-1", "position": 1, "title": "Airbag", "length": 284000,
        "recording": {"id": "rec-1", "title": "Airbag", "isrcs": ["GBAYE9701274"]},
        "artist-credit": [{"name": "Radiohead", "artist": {"id": "art-1"}}]}]}],
}


def _track(**tags) -> Track:
    return Track(id=1, path="/lib/Unknown Artist/track01.mp3", folder="/lib/Unknown Artist", duration=284.5, tags=tags)


def test_acoustid_match_on_untagged_file(monkeypatch):
    cands = candidates_from_acoustid(ACOUSTID)
    assert len(cands) == 1 and cands[0].fp_score == 0.97
    t = _track()
    ident = Identifier(db=None, settings=Settings(), task=__import__("musicmaid.progress").progress.NULL_TASK)
    matches = ident._resolve_folder([t], {t.id: cands})
    m = matches[0]
    # the original studio album wins over the compilation and the 2009 reissue
    assert m.release.release_id == "rel-okc"
    monkeypatch.setattr(mb, "get_release", lambda rid: RELEASE)
    ident._fill_tags(matches)
    assert m.tags["album"] == "OK Computer" and m.tags["tracknumber"] == "1"
    assert m.tags["label"] == "Parlophone" and m.tags["genre"] == "Alternative Rock"
    assert m.tags["acoustid_id"] == "acid-1" and m.tags["musicbrainz_albumid"] == "rel-okc"
    assert m.confidence >= 0.9  # strong fingerprint + matching length -> auto-apply


def test_wrong_tags_lower_confidence():
    cand = candidates_from_acoustid(ACOUSTID)[0]
    good = _track(title="Airbag", artist="Radiohead")
    wrong = _track(title="Some Other Song", artist="Someone Else")
    c_good, _ = confidence(good, cand, *query_tags(good, ["/lib"]))
    c_wrong, note = confidence(wrong, cand, *query_tags(wrong, ["/lib"]))
    assert c_good > c_wrong
    assert "differ" in note


def test_title_only_search_is_not_confident():
    from musicmaid.identify import Candidate
    t = _track(title="Airbag")
    cand = Candidate(recording_id="r", title="Airbag", artist="Some Band", length=284, search_score=1.0)
    conf, _ = confidence(t, cand, *query_tags(t, ["/lib"]))
    assert conf <= 0.6
