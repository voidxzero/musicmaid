from musicmaid.db import Track
from musicmaid.organizer import render
from musicmaid.textutil import (
    is_generic_title, norm, parse_filename, sanitize_component, similarity, smart_title_case,
)


def test_parse_filename_patterns():
    assert parse_filename("/m/Radiohead/OK Computer/01 - Airbag.mp3", "/m") == {
        "tracknumber": "1", "title": "Airbag", "album": "OK Computer", "artist": "Radiohead"}
    p = parse_filename("/m/Downloads/Radiohead - Karma Police.mp3", "/m")
    assert p == {"artist": "Radiohead", "title": "Karma Police"}  # 'Downloads' is not an album
    p = parse_filename("/m/Pink Floyd - The Wall (1979)/CD2/1-03 Hey You.flac", "/m")
    assert p["album"] == "The Wall" and p["date"] == "1979" and p["artist"] == "Pink Floyd"
    assert p["discnumber"] == "1" and p["tracknumber"] == "3" and p["title"] == "Hey You"
    # folders above the library root are never used
    assert "album" not in parse_filename("/home/me/music/song.mp3", "/home/me/music")


def test_text_helpers():
    assert smart_title_case("PARANOID ANDROID") == "Paranoid Android"
    assert smart_title_case("the end of the world") == "The End of the World"
    assert smart_title_case("McCartney II") == "McCartney II"  # mixed case untouched
    assert norm("The Beatles feat. Someone") == "beatles"
    assert norm("Song (Official Video)") == "song"
    assert similarity("Guns N' Roses", "Guns N Roses") > 0.9
    assert is_generic_title("Track 07") and is_generic_title("") and not is_generic_title("Seven")
    assert sanitize_component('AC/DC: "Live"?') == "AC-DC - _Live__"
    assert sanitize_component("CON") == "_CON"


def test_organizer_render():
    t = Track(id=1, path="/x/a.MP3", folder="/x", tags={
        "artist": "Radiohead", "albumartist": "Radiohead", "album": "OK Computer", "title": "Airbag",
        "tracknumber": "1", "date": "1997-06-16", "discnumber": "1", "totaldiscs": "1"})
    pat = "{albumartist}/{album} ({year})/{disc_prefix}{tracknumber:02} - {title}"
    assert render(pat, t) == "Radiohead/OK Computer (1997)/01 - Airbag.mp3"
    t.tags.update(discnumber="2", totaldiscs="2", title="What/Ever?")
    assert render(pat, t) == "Radiohead/OK Computer (1997)/2-01 - What-Ever_.mp3"
    t.tags.pop("date")
    t.tags.pop("tracknumber")
    assert render(pat, t) == "Radiohead/OK Computer/2-What-Ever_.mp3"
