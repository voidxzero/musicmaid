"""String normalisation, comparison, filename parsing and path sanitising."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

_FEAT_RE = re.compile(r"\s*[\(\[]?\s*\b(feat\.?|ft\.?|featuring|with)\b.*$", re.I)
_BRACKET_JUNK_RE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(official|video|audio|lyrics?|lyric video|hd|hq|4k|visualizer|explicit|clean|"
    r"remaster(ed)?|\d{4} remaster(ed)?|mono|stereo|radio edit|album version|bonus track)\b[^\)\]]*[\)\]]",
    re.I,
)
_URL_RE = re.compile(r"\s*[\(\[]?\s*(https?://|www\.)\S+\s*[\)\]]?", re.I)
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
GENERIC_TITLE_RE = re.compile(
    r"^\s*(track|audio ?track|piste|pista|titel|unknown|untitled|no title)?\s*[-_#]?\s*\d{0,3}\s*$", re.I
)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str | None, *, drop_feat: bool = True, drop_junk: bool = True) -> str:
    """Aggressive normalisation for comparing names."""
    if not s:
        return ""
    s = strip_accents(s).lower().replace("&", " and ")
    if drop_junk:
        s = _BRACKET_JUNK_RE.sub("", s)
    if drop_feat:
        s = _FEAT_RE.sub("", s)
    s = re.sub(r"^the\s+", "", s.strip())
    return _NON_ALNUM.sub(" ", s).strip()


def similarity(a: str | None, b: str | None) -> float:
    """0..1 similarity of two names after normalisation."""
    na, nb = norm(a), norm(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    # token containment helps with "Artist" vs "Artist & Someone"
    ta, tb = set(na.split()), set(nb.split())
    contain = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(ratio, contain * 0.9)


def is_generic_title(title: str | None) -> bool:
    if not title or not title.strip():
        return True
    return bool(GENERIC_TITLE_RE.match(title))


def clean_whitespace(s: str) -> str:
    return re.sub(r"\s{2,}", " ", s.replace(" ", " ")).strip()


def remove_urls(s: str) -> str:
    return clean_whitespace(_URL_RE.sub(" ", s))


_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of", "on", "or", "the", "to", "vs", "via", "de", "la", "le"}


def smart_title_case(s: str) -> str:
    """Title-case a string that is entirely upper- or lower-case. Leaves mixed case alone."""
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return s
    if not (all(c.isupper() for c in letters) or all(c.islower() for c in letters)):
        return s
    words = s.lower().split(" ")
    out = []
    for i, w in enumerate(words):
        if i not in (0, len(words) - 1) and w in _SMALL_WORDS:
            out.append(w)
        elif re.fullmatch(r"[ivxlcdm]+", w) and len(w) <= 4 and w not in ("mix", "dim", "mid", "did", "ill", "li", "civil"):
            out.append(w.upper())  # roman numerals
        else:
            out.append(re.sub(r"(^|[-(\[/\"'])([a-z])", lambda m: m.group(1) + m.group(2).upper(), w))
    return " ".join(out)


# ---------------------------------------------------------------- filename parsing
_TRACKNO = r"(?P<track>\d{1,3})"
_FILENAME_PATTERNS = [
    # 01 - Artist - Title
    re.compile(rf"^{_TRACKNO}\s*[-._)]\s*(?P<artist>.+?)\s+-\s+(?P<title>.+)$"),
    # 1-01 Title (disc-track)
    re.compile(r"^(?P<disc>\d)[-.](?P<track>\d{2})\s*[-._]?\s*(?P<title>.+)$"),
    # 01 - Title / 01. Title / 01 Title
    re.compile(rf"^{_TRACKNO}\s*[-._)]?\s+(?P<title>.+)$"),
    # Artist - 01 - Title
    re.compile(rf"^(?P<artist>.+?)\s+-\s+{_TRACKNO}\s+-\s+(?P<title>.+)$"),
    # Artist - Title
    re.compile(r"^(?P<artist>.+?)\s+-\s+(?P<title>.+)$"),
]


_GENERIC_DIRS = re.compile(
    r"^(downloads?|unsorted|incoming|new folder( \(\d+\))?|music|my music|musique|musik|misc|various|mp3s?|flac|"
    r"audio|songs|tracks|temp|tmp|backup|backups|desktop|documents|home|library|collection|singles|torrents?|"
    r"complete|completed|to sort|sort|inbox|media|share|shared|users?|mnt|data|storage|"
    r"unknown|unknown artist|unknown album|various artists|untitled|[a-z]:)$",
    re.I,
)


def _useful_dir(name: str) -> bool:
    return bool(name) and not _GENERIC_DIRS.match(name.strip())


def parse_filename(path: str | Path, root: str | Path | None = None) -> dict[str, str]:
    """Guess tags from a file path such as 'Artist/Album/01 - Title.mp3'.

    Folder names are only used when they sit below ``root`` (the library folder)
    and don't look like generic folders such as 'Downloads'.
    """
    p = Path(path)
    stem = clean_whitespace(p.stem.replace("_", " "))
    stem = _URL_RE.sub("", stem).strip()
    out: dict[str, str] = {}
    for pat in _FILENAME_PATTERNS:
        m = pat.match(stem)
        if m:
            for k, v in m.groupdict().items():
                if v:
                    out[k] = v.strip(" -.")
            break
    else:
        out["title"] = stem
    if "track" in out:
        out["tracknumber"] = str(int(out.pop("track")))
    if "disc" in out:
        out["discnumber"] = str(int(out.pop("disc")))

    dirs: list[str] = []
    d = p.parent
    root_p = Path(root) if root else None
    while d != d.parent and len(dirs) < 3:
        if root_p is not None and (d == root_p or root_p not in d.parents):
            break
        dirs.append(d.name)
        d = d.parent
    if dirs and re.fullmatch(r"(cd|disc|disk)\s*\d+", dirs[0], re.I):
        m = re.search(r"\d+", dirs[0])
        out.setdefault("discnumber", str(int(m.group(0))))
        dirs = dirs[1:]
    parent = dirs[0] if dirs else ""
    grand = dirs[1] if len(dirs) > 1 else ""
    if _useful_dir(parent):
        m = re.match(r"^(?P<artist>.+?)\s+-\s+(?P<album>.+?)(\s*[\(\[](?P<year>\d{4})[\)\]])?$", parent)
        if m:
            out.setdefault("artist", m.group("artist"))
            out["album"] = m.group("album")
            if m.group("year"):
                out["date"] = m.group("year")
        elif _useful_dir(grand):
            m = re.match(r"^(?:(?P<y1>\d{4})\s*-\s*)?(?P<album>.+?)\s*(?:[\(\[](?P<year>\d{4})[\)\]])?$", parent)
            out["album"] = m.group("album") if m else parent
            if m and (m.group("year") or m.group("y1")):
                out["date"] = m.group("year") or m.group("y1")
            out.setdefault("artist", grand)
    for k in list(out):
        out[k] = clean_whitespace(out[k])
    return out


# ---------------------------------------------------------------- path sanitising
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_component(s: str, max_len: int = 120) -> str:
    """Make a single path component safe on Windows and Linux."""
    s = _BAD_CHARS.sub("_", s.replace(": ", " - ").replace("/", "-"))
    s = clean_whitespace(s).rstrip(". ")
    if not s:
        s = "_"
    if s.upper().split(".")[0] in _WIN_RESERVED:
        s = "_" + s
    if len(s) > max_len:
        s = s[:max_len].rstrip(". ")
    return s


def first_int(v: str | None) -> int | None:
    if not v:
        return None
    m = re.match(r"\s*(\d+)", str(v))
    return int(m.group(1)) if m else None


def year_of(v: str | None) -> str:
    m = re.search(r"\d{4}", v or "")
    return m.group(0) if m else ""
