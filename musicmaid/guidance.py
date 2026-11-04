"""User-facing explanations shared by the GUI, TUI and CLI."""

ACOUSTID_SIGNUP = "https://acoustid.org/new-application"

ACOUSTID_INTRO = (
    "MusicMaid recognises songs by their sound using AcoustID, a free service for open-source apps. "
    "It works out of the box with MusicMaid's own key. You only need a key of your own if you'd rather "
    "use one (get it free at " + ACOUSTID_SIGNUP + ")."
)

ACOUSTID_WITH = (
    "Recognising by sound means even untagged files, wrongly tagged files and files with meaningless "
    "names (\"Track 01.mp3\") get the right title, artist and album. It needs Chromaprint's fpcalc, which "
    "the standalone apps include and MusicMaid offers to download otherwise."
)

ACOUSTID_WITHOUT = (
    "Everything else works without it too (clean-up, artwork, duplicates, organizing): songs are then "
    "identified from their existing tags, MusicBrainz IDs and file/folder names."
)

ACOUSTID_PRIVACY = (
    "Only the audio fingerprint and length of each file are sent, never the audio itself."
)
