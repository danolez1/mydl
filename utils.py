def _nz(value, fallback=0):
    """Return *value* if it is a number; otherwise *fallback*."""
    return value if isinstance(value, (int, float)) else fallback


def pick_best(formats):
    """
    Return (best_progressive_av, best_audio_only).

    * The A/V candidate is **always** a progressive format (video *and* audio
      together) – no later merging is required.
    * The audio candidate is **always** an audio-only format.
    * If one of them cannot be found at the first try the function keeps
      stepping down the quality list **only** for the missing one, until it
      succeeds or there are no more suitable formats left.
    """

    # -------------------------
    # 1. Build two candidate lists
    # -------------------------
    progressive = [
        f for f in formats
        if f.get("vcodec") not in (None, "none")        # has video
        and f.get("acodec") not in (None, "none")       # …and audio
        and f.get("ext") != "mhtml"                     # skip data-URI frames, etc.
    ]
    audio_only = [
        f for f in formats
        if f.get("vcodec") in (None, "none")            # no video
        and f.get("acodec") not in (None, "none")       # but has audio
    ]

    # -------------------------
    # 2. Sort them once – highest quality first
    # -------------------------
    progressive.sort(
        key=lambda f: (_nz(f.get("height")), _nz(f.get("tbr"))),
        reverse=True,
    )
    audio_only.sort(
        key=lambda f: _nz(f.get("abr", f.get("tbr"))),
        reverse=True,
    )

    # -------------------------
    # 3. Walk the lists, falling back only on the side that is missing
    # -------------------------
    idx_p, idx_a = 0, 0              # current position in each list

    while True:
        best_av     = progressive[idx_p] if idx_p < len(progressive) else None
        best_audio  = audio_only[idx_a] if idx_a < len(audio_only) else None

        # Success: both sides found
        if best_av is not None and best_audio is not None:
            return best_av, best_audio

        # Permanent failure on the missing side – nothing more to try
        if best_av is None and idx_p >= len(progressive):
            return None, best_audio          # no progressive A/V available
        if best_audio is None and idx_a >= len(audio_only):
            return best_av, None             # no audio-only available

        # Advance **only** the side that is still missing
        if best_av is None:
            idx_p += 1
        else:                                # best_audio is None
            idx_a += 1