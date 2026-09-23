"""Spotify playback control via the official Web API (spotipy).

Tool functions exposed to the model:
- spotify_play / spotify_pause            — resume / pause;
- spotify_next / spotify_previous         — next / previous track;
- spotify_play_track(query)               — search a track by name and play it;
- spotify_play_liked                      — the user's Liked Songs, shuffled.

Design (see Phase 6 ADR):
- spotipy handles OAuth (Authorization Code) and token refresh.
- Authorization Code flow — playback is controlled ON BEHALF of the user, so it
  needs their login and a refresh token (not Client Credentials).
- Token cache: .spotify_cache at the project root (gitignored: holds the
  refresh token). Consent once in the browser, then reused from the cache.
- Secrets (Client ID/Secret/Redirect) come from .env via python-dotenv, never code.
- Minimal scope: playback control + playback state + library read (liked songs).
- 403s are NOT guessed: apart from Premium/scope we return Spotify's verbatim reason.

Volume is NOT here: it stays with the system tools (pycaw, src/tools/audio.py)
so the two never overlap in routing.

The client is created LAZILY (on first call), so importing this module at
startup opens no browser and needs no network — login happens on first command.

Expected external-API failures return a friendly string (the model will voice
it), not a traceback: no active device (404), no Premium (403), auth or network.
"""

from __future__ import annotations

import functools
import os
import random
from pathlib import Path

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
from spotipy.cache_handler import CacheFileHandler
from dotenv import load_dotenv

# --- Configuration ----------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Secrets come from .env at the project root (SPOTIPY_CLIENT_ID / _SECRET /
# _REDIRECT_URI). SpotifyOAuth reads these environment variables itself.
load_dotenv(PROJECT_ROOT / ".env")

_CACHE_PATH = PROJECT_ROOT / ".spotify_cache"
# user-library-read is for Liked Songs (spotify_play_liked). Changing the scope
# triggers a one-time re-consent in the browser: spotipy sees the cached token
# doesn't cover the new scope and asks to log in again.
_SCOPE = (
    "user-modify-playback-state user-read-playback-state user-library-read"
)

# How many most recent Liked Songs to queue (shuffled).
_LIKED_LIMIT = 100

# Country (ISO 3166-1 alpha-2) for track availability filtering. An explicit
# code, NOT "from_token": from_token needs scope user-read-private, without it
# search fails with 403 "Insufficient client scope". Override in .env.
_MARKET = os.getenv("SPOTIFY_MARKET", "CA")

# Lazy singleton client — created on first use.
_client: spotipy.Spotify | None = None

_NO_DEVICE = (
    "No active Spotify device. Open Spotify on your phone or computer "
    "and try again."
)


def _get_client() -> spotipy.Spotify:
    """Return (creating if needed) an authorised Spotify client.

    The first call runs a one-time browser consent; afterwards the token is
    read from .spotify_cache and refreshed automatically.
    """
    global _client
    if _client is None:
        auth_manager = SpotifyOAuth(
            scope=_SCOPE,
            cache_handler=CacheFileHandler(cache_path=str(_CACHE_PATH)),
            open_browser=True,
        )
        _client = spotipy.Spotify(auth_manager=auth_manager)
    return _client


# --- Expected external-API errors -------------------------------------------


def _spotify_detail(exc: spotipy.SpotifyException) -> str:
    """Spotify's error text without the URL prefix.

    spotipy puts "<url>:\\n <message>" into exc.msg — the last line is the
    actual Spotify message ("Restriction violated", etc.).
    """
    raw = getattr(exc, "msg", None) or ""
    return raw.strip().splitlines()[-1].strip() if raw.strip() else "unknown"


def _friendly_errors(func):
    """Decorator: turn expected Spotify failures into a clear string.

    The choke point in handle_turn catches any raise anyway, but for EXPECTED
    errors we return meaningful text the assistant can voice.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except spotipy.SpotifyException as exc:
            status = getattr(exc, "http_status", None)
            if status == 404:
                return _NO_DEVICE
            detail = _spotify_detail(exc)
            if status == 403:
                # Spotify's 403 means MANY things — never guess the category
                # (we got it wrong twice). Recognise only the two cases with a
                # clear user action; everything else is Spotify's verbatim reason.
                reason = (getattr(exc, "reason", None) or "").upper()
                low = detail.lower()
                if reason == "PREMIUM_REQUIRED" or "premium required" in low:
                    return (
                        "Playback control requires Spotify Premium — the API "
                        "rejects free accounts."
                    )
                if "insufficient client scope" in low:
                    return (
                        "The assistant lacks Spotify permissions. Delete "
                        ".spotify_cache and restart — Spotify will ask to log in again."
                    )
                return f"Spotify rejected the command. Spotify's reason: {detail}"
            return f"Spotify error ({status}). Spotify's reason: {detail}"
        except SpotifyOauthError:
            return (
                "Spotify authorisation failed — check the keys in .env and "
                "log in again."
            )
        except requests.exceptions.RequestException:
            return "Spotify is unreachable right now — network problem."

    return wrapper


# --- Tool functions ---------------------------------------------------------


@_friendly_errors
def spotify_play() -> str:
    """Resume Spotify playback.

    Use ONLY to continue what was paused: "resume", "unpause", «продолжи
    музыку», «сними с паузы», «продовж музику».
    Do NOT use for "play my music" / "liked songs" / «включи мою музыку» —
    that is spotify_play_liked. For a specific song use spotify_play_track.
    """
    sp = _get_client()
    state = sp.current_playback()
    if state is None:
        return _NO_DEVICE
    if state.get("is_playing"):
        # Spotify rejects resume with 403 while already playing — so don't
        # send a pointless command, just report the state.
        return "Music is already playing."
    try:
        sp.start_playback()
    except spotipy.SpotifyException as exc:
        # 403 "Restriction violated" on resume = nothing to resume (a single
        # track ended, track unavailable in region, etc.). Only this exact
        # reason — other 403s (Premium, scope) go to the generic handler.
        if exc.http_status == 403 and "restriction violated" in _spotify_detail(exc).lower():
            return (
                "Nothing to resume — the queue has ended. Name a track or "
                "ask to play your music."
            )
        raise
    return "Music is playing."


@_friendly_errors
def spotify_pause() -> str:
    """Pause Spotify playback.

    Use for "pause", "stop", «пауза», «останови музыку», «постав на паузу».
    """
    sp = _get_client()
    state = sp.current_playback()
    if state is None:
        return _NO_DEVICE
    if not state.get("is_playing"):
        return "Music is already paused."
    sp.pause_playback()
    return "Paused."


@_friendly_errors
def spotify_next() -> str:
    """Skip to the next Spotify track.

    Use for "next", "skip", «следующий трек», «дальше», «наступний трек».
    """
    _get_client().next_track()
    return "Next track."


@_friendly_errors
def spotify_previous() -> str:
    """Go back to the previous Spotify track.

    Use for "previous", "back", «предыдущий трек», «назад», «попередній трек».
    """
    _get_client().previous_track()
    return "Previous track."


@_friendly_errors
def spotify_play_track(query: str) -> str:
    """Search a track by title/artist and play it on Spotify.

    Use when the user names WHAT to play: "play Blinding Lights",
    «включи Bohemian Rhapsody», «постав пісню Океан Ельзи»,
    «включи что-нибудь из Radiohead».

    query: track title and/or artist, e.g. "Bohemian Rhapsody Queen".
    """
    if not query or not query.strip():
        return "No track specified."
    sp = _get_client()
    # market = only tracks available in the account's country; otherwise search
    # may return an unavailable track and Spotify silently stops.
    results = sp.search(
        q=query.strip(), type="track", limit=5, market=_MARKET
    )
    items = results.get("tracks", {}).get("items", [])
    playable = [t for t in items if t and t.get("is_playable", True)]
    if not playable:
        return f"No playable track found for '{query}'."
    track = playable[0]
    name = track["name"]
    artist = track["artists"][0]["name"] if track.get("artists") else "?"
    album_uri = (track.get("album") or {}).get("uri")
    if album_uri:
        # Play the track IN ITS ALBUM CONTEXT so music continues through the
        # album instead of stopping (a bare uris=[...] is a queue of one).
        sp.start_playback(context_uri=album_uri, offset={"uri": track["uri"]})
    else:
        sp.start_playback(uris=[track["uri"]])
    return f"Playing: {name} — {artist} (the album continues after it)."


@_friendly_errors
def spotify_play_liked() -> str:
    """Play the user's Liked Songs, shuffled.

    Use for "play my music", "play my liked songs", "play liked songs"
    (speech recognition may produce "like it songs" / "liked it songs"),
    «включи мою музыку», «мои любимые треки», «включи мои лайки»,
    «увімкни мою музику», «мої вподобані треки».
    """
    sp = _get_client()
    uris: list[str] = []
    offset = 0
    while len(uris) < _LIKED_LIMIT:
        page = sp.current_user_saved_tracks(
            limit=50, offset=offset, market=_MARKET
        )
        items = page.get("items", [])
        if not items:
            break
        for item in items:
            track = item.get("track") or {}
            # The Web API can't play local files; skip unavailable tracks too.
            if (
                track.get("uri")
                and not track.get("is_local")
                and track.get("is_playable", True)
            ):
                uris.append(track["uri"])
        if not page.get("next"):
            break
        offset += 50
    if not uris:
        return "Liked Songs is empty or nothing in it is playable."
    uris = uris[:_LIKED_LIMIT]
    random.shuffle(uris)
    sp.start_playback(uris=uris)
    return f"Playing your liked songs, shuffled ({len(uris)} tracks)."
