from datetime import datetime
from src.tools.timer import set_timer
import ollama

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
from src.tools.audio import switch_audio_device

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

init_db()

session_id = create_session()
today = datetime.now().strftime("%Y-%m-%d")

available_functions = {
    "add_item": add_item,
    "list_items": list_items,
    "update_item_status": update_item_status,
    "touch_last_accessed": touch_last_accessed,
    "switch_audio_device": switch_audio_device,
    "set_timer": set_timer,
}

# Build the system prompt. Inject last session summary if available.
last_summary = get_last_session_summary()
system_content = f"Today's date: {today}. Use it as reference when user mentions a date without a year."
if last_summary:
    system_content += f"\n\nContext from your last session:\n{last_summary}"

messages: list[dict] = [
    {"role": "system", "content": system_content},
]

# Load recent message history from DB and append after system prompt
recent = load_recent_messages(limit=30)
if recent:
    messages.extend(recent)
    print(f"[INFO] Loaded {len(recent)} messages from previous sessions.\n")

print("Assistant started. Type messages, 'exit' or 'quit' to stop.\n")

# Track only the NEW messages added in this session (for saving at exit)
new_messages: list[dict] = []

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

while True:
    user_input = input("You: ")

    if user_input.strip().lower() in ("exit", "quit"):
        break

    user_msg = {"role": "user", "content": user_input}
    messages.append(user_msg)
    new_messages.append(user_msg)

    response = ollama.chat(
        model="gemma4-assistant",
        messages=messages,
        tools=[
            add_item,
            list_items,
            update_item_status,
            touch_last_accessed,
            switch_audio_device,
            set_timer,
        ],
    )

    messages.append(response.message)

    if response.message.tool_calls:
        for tool_call in response.message.tool_calls:
            fn_name = tool_call.function.name
            fn_args = tool_call.function.arguments
            print(f"[DEBUG] Call: {fn_name}, args: {fn_args}")

            function_to_call = available_functions[fn_name]
            result = function_to_call(**fn_args)
            print(f"[DEBUG] Result: {result}")

            tool_result_msg = {
                "role": "tool",
                "content": repr(result),
                "tool_name": fn_name,
            }
            messages.append(tool_result_msg)
            new_messages.append(tool_result_msg)

        final_response = ollama.chat(
            model="gemma4-assistant",
            messages=messages,
            tools=[
                add_item,
                list_items,
                update_item_status,
                touch_last_accessed,
                switch_audio_device,
                set_timer,
            ],
        )
        messages.append(final_response.message)

        assistant_msg = {"role": "assistant", "content": final_response.message.content}
        new_messages.append(assistant_msg)
        print(f"Assistant: {final_response.message.content}\n")
    else:
        assistant_msg = {"role": "assistant", "content": response.message.content}
        new_messages.append(assistant_msg)
        print(f"Assistant: {response.message.content}\n")

# ---------------------------------------------------------------------------
# Shutdown — save history, close session
# ---------------------------------------------------------------------------

save_messages(session_id, new_messages)
close_session(session_id, summary=None)  # summary=None until phase 2
print("[INFO] Session saved. Goodbye.")