import sys

# Force UTF-8 on the standard streams so RU/UK (Cyrillic) output can't crash the
# assistant on a legacy console code page — e.g. when the tray launches this via
# powershell.exe rather than an interactive UTF-8 terminal. Guarded: no-op if a
# stream can't be reconfigured (redirected to a pipe, etc.).
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

import argparse
import time
from datetime import datetime

import ollama

from src.logging_config import setup_logging
from src.tools.timer import set_timer
from src.tools.weather import get_weather, set_weather_location
from src.tools.spotify import (
    spotify_play,
    spotify_pause,
    spotify_next,
    spotify_previous,
    spotify_play_track,
    spotify_play_liked,
)
from src.db.database import (
    init_db,
    add_item,
    list_items,
    update_item_status,
    touch_last_accessed,
    create_session,
    close_session,
    save_messages,
    load_recent_messages,
    get_last_session_summary,
)
from src.tools.audio import (
    switch_audio_device,
    set_volume,
    get_volume,
    change_volume,
    volume_up,
    volume_down,
    set_mute,
    get_mute,
)

MODEL = "gemma4-assistant"

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

# Configure logging before anything else so every subsequent line — DB init,
# tool calls, errors — lands in logs/assistant.log with a timestamp.
logger = setup_logging()
logger.info("=== assistant starting ===")

init_db()

session_id = create_session()
today = datetime.now().strftime("%Y-%m-%d")
logger.info("session created: %s", session_id)

available_functions = {
    "add_item": add_item,
    "list_items": list_items,
    "update_item_status": update_item_status,
    "touch_last_accessed": touch_last_accessed,
    "switch_audio_device": switch_audio_device,
    "set_timer": set_timer,
    "set_volume": set_volume,
    "get_volume": get_volume,
    "change_volume": change_volume,
    "volume_up": volume_up,
    "volume_down": volume_down,
    "set_mute": set_mute,
    "get_mute": get_mute,
    "get_weather": get_weather,
    "set_weather_location": set_weather_location,
    "spotify_play": spotify_play,
    "spotify_pause": spotify_pause,
    "spotify_next": spotify_next,
    "spotify_previous": spotify_previous,
    "spotify_play_track": spotify_play_track,
    "spotify_play_liked": spotify_play_liked,
}

# Single source of truth for the model's tool set. Deriving the list from the
# dict guarantees both ollama.chat calls stay in sync — a tool added to
# available_functions is automatically offered to the model.
TOOLS = list(available_functions.values())


# ---------------------------------------------------------------------------
# Memory-durability policy (Phase 0.5, Task B)
# ---------------------------------------------------------------------------
# Classify a turn by WHAT IT DID, not what words it contained (language-proof
# across RU/UK/EN, zero maintenance). A turn is TRANSIENT iff it called at
# least one tool AND every tool it called is ephemeral (a pure action with
# nothing worth remembering). Everything else is DURABLE — plain conversation
# (no tools) and any turn that touched a durable tool, including a mixed turn
# like "turn it up and remind me to call mom".
#
# TRANSIENT turns stay in the live `messages` list so within-session follow-ups
# still resolve ("громче" then "ещё немного"), but they are NOT written to the
# DB at shutdown, so they don't bloat storage or crowd the reloaded context.
EPHEMERAL_TOOLS = frozenset({
    "set_volume", "get_volume", "change_volume", "volume_up", "volume_down",
    "set_mute", "get_mute", "switch_audio_device", "set_timer",
    # A weather forecast is transient info — no value reloading it into context.
    "get_weather",
    # Spotify playback controls are pure actions — nothing worth persisting.
    "spotify_play", "spotify_pause", "spotify_next", "spotify_previous",
    "spotify_play_track", "spotify_play_liked",
})
DURABLE_TOOLS = frozenset({
    "add_item", "list_items", "update_item_status", "touch_last_accessed",
    # Changing the default weather city is a saved preference — worth keeping.
    "set_weather_location",
})


def _is_transient_turn(called_tools: set[str]) -> bool:
    """
    True iff the turn called >= 1 tool and every called tool is ephemeral.

    Any call to a durable tool, an unknown/hallucinated tool name, or no tool
    at all -> not transient (i.e. DURABLE, persisted). This is the safe default:
    when in doubt, keep the turn.
    """
    return bool(called_tools) and called_tools <= EPHEMERAL_TOOLS


# ---------------------------------------------------------------------------
# One conversational turn (input-source-agnostic)
# ---------------------------------------------------------------------------

def handle_turn(user_text: str, messages: list[dict], new_messages: list[dict]) -> str:
    """
    Process one user utterance and return the assistant's reply text.

    The text can come from the keyboard or from a speech-to-text transcript
    (voice layer) — this function does not care which. It always appends the
    turn to `messages` (live context). Whether the turn is also committed to
    `new_messages` (the shutdown-persisted log) depends on its durability: a
    transient action-only turn is kept live but dropped from the saved log.
    """
    user_msg = {"role": "user", "content": user_text}
    messages.append(user_msg)

    # Buffer this turn's persist-worthy messages here and commit them to
    # new_messages only once we know the turn is durable. `messages` (live
    # context) always gets every message, regardless of durability.
    turn_messages: list[dict] = [user_msg]
    called_tools: set[str] = set()

    response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
    messages.append(response.message)

    # No tool calls: the model answered directly. Plain conversation is durable.
    if not response.message.tool_calls:
        reply = response.message.content
        turn_messages.append({"role": "assistant", "content": reply})
        new_messages.extend(turn_messages)
        logger.info("turn persisted (durable, no tools)")
        return reply

    # Tool calls: execute each, feed results back, then get the phrased reply.
    for tool_call in response.message.tool_calls:
        fn_name = tool_call.function.name
        fn_args = tool_call.function.arguments
        called_tools.add(fn_name)
        logger.info("tool call: %s args=%s", fn_name, fn_args)

        # Single choke point: an unknown tool or a raising tool reports the
        # error back to the model instead of crashing the assistant.
        function_to_call = available_functions.get(fn_name)
        if function_to_call is None:
            result = f"[ERROR] Unknown tool: {fn_name}"
            logger.error("unknown tool: %s", fn_name)
        else:
            try:
                result = function_to_call(**fn_args)
            except Exception:
                # Full traceback to the log; a compact error string to the model.
                logger.exception("tool %s raised", fn_name)
                result = f"[ERROR] {fn_name} failed"
        logger.info("tool result: %s -> %r", fn_name, result)

        tool_result_msg = {
            "role": "tool",
            "content": repr(result),
            "tool_name": fn_name,
        }
        messages.append(tool_result_msg)
        turn_messages.append(tool_result_msg)

    final_response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
    messages.append(final_response.message)
    reply = final_response.message.content
    turn_messages.append({"role": "assistant", "content": reply})

    # Structural durability decision (see EPHEMERAL_TOOLS above).
    if _is_transient_turn(called_tools):
        logger.info(
            "turn TRANSIENT (tools=%s) — kept in session, not persisted",
            sorted(called_tools),
        )
    else:
        new_messages.extend(turn_messages)
        logger.info("turn persisted (durable, tools=%s)", sorted(called_tools))

    return reply


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

last_summary = get_last_session_summary()
system_content = (
    f"Today's date: {today}. Use it as reference when user mentions a date without a year.\n"
    "Always reply in the language of the user's latest message (Russian, Ukrainian "
    "or English). Tool results are in English — translate them, don't switch language."
)
if last_summary:
    system_content += f"\n\nContext from your last session:\n{last_summary}"

messages: list[dict] = [
    {"role": "system", "content": system_content},
]

recent = load_recent_messages(limit=30)
if recent:
    messages.extend(recent)
    logger.info("loaded %d messages from previous sessions", len(recent))

# Track only the NEW messages added in this session (for saving at exit)
new_messages: list[dict] = []


# ---------------------------------------------------------------------------
# Main loop — voice by default (hold F9), or --text to type. Both feed handle_turn.
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser()
parser.add_argument("--text", action="store_true",
                    help="Type input instead of holding F9 to speak.")
args = parser.parse_args()

if args.text:
    print("Text mode. Type a message; 'exit'/'quit' to stop.\n")
    logger.info("input mode: text")
    while True:
        user_input = input("You: ")
        if user_input.strip().lower() in ("exit", "quit"):
            break
        reply = handle_turn(user_input, messages, new_messages)
        print(f"Assistant: {reply}\n")
else:
    import keyboard
    from src.voice.recorder import _Recorder, PTT_KEY, SAMPLE_RATE
    from src.voice.stt import transcribe, warm_up

    logger.info("input mode: voice (PTT)")
    warm_up()  # load large-v3 into VRAM now, so the first F9 press is instant
    _recorder = _Recorder()
    print(f"Hold {PTT_KEY.upper()} to speak. Ctrl+C to quit.\n")

    try:
        while True:
            if keyboard.is_pressed(PTT_KEY):
                try:
                    audio = _recorder.record_while(lambda: keyboard.is_pressed(PTT_KEY))

                    if len(audio) < SAMPLE_RATE // 2:      # under ~0.5s — a mis-tap
                        print("[voice] (too short, ignored)\n")
                        continue

                    text, lang = transcribe(audio)
                    if not text.strip():                    # no speech recognised
                        print("[voice] (nothing recognised)\n")
                        continue

                    logger.info("transcript (lang=%s): %s", lang, text)
                    print(f"You (voice, {lang}): {text}")
                    reply = handle_turn(text, messages, new_messages)
                    print(f"Assistant: {reply}\n")
                except Exception:
                    # One bad utterance shouldn't kill the session.
                    logger.exception("voice turn failed")

            time.sleep(0.03)   # ~33 Hz idle poll; keeps CPU near zero
    except KeyboardInterrupt:
        logger.info("stopping (KeyboardInterrupt)")


# ---------------------------------------------------------------------------
# Shutdown — save history, close session
# ---------------------------------------------------------------------------

save_messages(session_id, new_messages)
close_session(session_id, summary=None)  # summary=None until phase 2
logger.info("session saved (%d messages persisted). Goodbye.", len(new_messages))
