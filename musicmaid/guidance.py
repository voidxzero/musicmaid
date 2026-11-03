"""User-facing explanations shared by the GUI, TUI and CLI."""

ACOUSTID_SIGNUP = "https://acoustid.org/new-application"

ACOUSTID_INTRO = (
    "MusicMaid can recognise songs by their sound using AcoustID, a free service for open-source apps. "
    "It needs a free AcoustID key, which you get in a minute at " + ACOUSTID_SIGNUP + ": sign in, enter "
    "any application name (e.g. \"MusicMaid\") and copy the API key."
)

ACOUSTID_WITH = (
    "With a key: files are identified by their audio, so even untagged files, wrongly tagged files and "
    "files with meaningless names (\"Track 01.mp3\") get the right title, artist and album."
)

ACOUSTID_WITHOUT = (
    "Without a key: everything else still works (clean-up, artwork, duplicates, organizing). Songs are "
    "identified from their existing tags, MusicBrainz IDs and file/folder names. That works well for "
    "roughly-tagged music, but files with no useful tags or names end up in \"Needs review\" for you "
    "to fix by hand."
)

ACOUSTID_PRIVACY = (
    "Only the audio fingerprint and length of each file are sent, never the audio itself. "
    "You can add or remove the key any time in Settings."
)
