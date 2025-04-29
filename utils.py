def _nz(value, fallback=0):
    """Return *value* if it is a number; otherwise *fallback*."""
    return value if isinstance(value, (int, float)) else fallback


def pick_best(formats):
    """Return (best_progressive_av, best_audio_only)."""
    progressive = [
        f for f in formats
        if f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
        and f.get("ext") != "mhtml"                 # skip data-URI frames, etc.
    ]
    audio_only = [
        f for f in formats
        if f.get("vcodec") in (None, "none")
        and f.get("acodec") not in (None, "none")
    ]

    best_av = max(progressive, key=lambda f: (_nz(f.get("height")), _nz(f.get("tbr"))), default=None)
    best_audio = max(audio_only, key=lambda f: _nz(f.get("abr", f.get("tbr"))), default=None)
    return best_av, best_audio
