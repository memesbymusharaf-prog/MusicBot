import os
import asyncio
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped
from yt_dlp import YoutubeDL
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("frozen.env")

# ==================== CONFIG ====================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
STRING_SESSION = os.getenv("STRING_SESSION")
MONGO_URL = os.getenv("MONGO_URL")
OWNER_ID = int(os.getenv("OWNER_ID"))
LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID", -100))

# Premium Emoji IDs (Same as your bot)
EMOJI = {
    "loading": "6289785914851859832",
    "money": "5429651785352501917",
    "pin": "5382164415019768638",
    "star": "5267500801240092311",
    "plane": "5298719183347932250",
    "rocket": "5201691993775818138",
    "check": "5370972705203966197",
    "crown": "5433758796289685818",
    "shopping": "5193177581888755275",
    "heart": "5195033767969839232",
    "fire": "5451636889717062286",
    "phone": "5370972705203966197",
    "play": "6267225207560214192",
    "pause": "6267000941547885720",
    "skip": "6237718408574539239",
    "stop": "5408889020090449272",
    "queue": "5289519844436234080",
    "loop": "5472026645659401564"
}

def emoji(emoji_id, fallback):
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

# ==================== INIT ====================
app = Client(
    "frozen_music",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# User client with string session (for better voice chat)
user_client = Client(
    "user_client",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION
)

call = PyTgCalls(user_client)

# MongoDB
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client.frozen_music
users_col = db.users
chats_col = db.chats
playlist_col = db.playlists

# Queue System
queues = {}
current_playing = {}
loop_status = {}

# ==================== HELPERS ====================
async def is_admin(chat_id, user_id):
    chat = await app.get_chat(chat_id)
    member = await chat.get_member(user_id)
    return member.status in ["creator", "administrator"] or user_id == OWNER_ID

async def download_audio(url):
    os.makedirs("downloads", exist_ok=True)
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'extractaudio': True,
        'audioformat': 'mp3',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            filename = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
            return filename, info['title'], info.get('duration', 0)
    except Exception as e:
        print(f"Download error: {e}")
        return None, None, None

async def get_youtube_url(query):
    ydl_opts = {'format': 'bestaudio/best', 'quiet': True, 'no_warnings': True}
    try:
        with YoutubeDL(ydl_opts) as ydl:
            if 'youtube.com' in query or 'youtu.be' in query:
                info = ydl.extract_info(query, download=False)
                return query, info['title'], info.get('duration', 0)
            else:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)
                if info.get('entries'):
                    video = info['entries'][0]
                    return video['webpage_url'], video['title'], video.get('duration', 0)
    except Exception as e:
        print(f"Search error: {e}")
    return None, None, None

async def play_song(chat_id, url, title, duration):
    try:
        audio_file, _, _ = await download_audio(url)
        if audio_file:
            await call.change_stream(chat_id, AudioPiped(audio_file))
            current_playing[chat_id] = {'title': title, 'duration': duration, 'url': url}
            
            # Keyboard with colors and premium emojis
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        text=f"{emoji(EMOJI['pause'], '⏸')} Pause",
                        callback_data="pause",
                        style="primary"
                    ),
                    InlineKeyboardButton(
                        text=f"{emoji(EMOJI['play'], '▶️')} Resume",
                        callback_data="resume",
                        style="success"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{emoji(EMOJI['skip'], '⏭')} Skip",
                        callback_data="skip",
                        style="danger"
                    ),
                    InlineKeyboardButton(
                        text=f"{emoji(EMOJI['loop'], '🔁')} Loop",
                        callback_data="loop",
                        style="primary"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{emoji(EMOJI['queue'], '📜')} Queue",
                        callback_data="queue",
                        style="primary"
                    ),
                    InlineKeyboardButton(
                        text=f"{emoji(EMOJI['stop'], '🗑')} Stop",
                        callback_data="stop",
                        style="danger"
                    )
                ]
            ])
            
            duration_str = f"{duration//60}:{duration%60:02d}"
            await app.send_message(
                chat_id,
                f"{emoji(EMOJI['play'], '🎵')} <b>Now Playing</b>\n\n"
                f"<b>Title:</b> {title}\n"
                f"<b>Duration:</b> {duration_str}\n\n"
                f"{emoji(EMOJI['heart'], '❤️')} <b>Enjoy the music!</b>",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return True
    except Exception as e:
        print(f"Play error: {e}")
    return False

async def play_next(chat_id):
    if chat_id in queues and queues[chat_id]:
        next_song = queues[chat_id].pop(0)
        await play_song(chat_id, next_song['url'], next_song['title'], next_song['duration'])
    else:
        current_playing.pop(chat_id, None)
        await call.leave_call(chat_id)

# ==================== COMMANDS ====================
@app.on_message(filters.command("start"))
async def start_command(client, message):
    user_id = message.from_user.id
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"username": message.from_user.username, "last_active": datetime.now()}},
        upsert=True
    )
    
    await message.reply_text(
        f"{emoji(EMOJI['fire'], '🔥')} <b>Frozen Music Bot</b> {emoji(EMOJI['fire'], '🔥')}\n\n"
        f"{emoji(EMOJI['check'], '✅')} <b>Commands:</b>\n"
        f"• /play <song/url> - Play music\n"
        f"• /pause - Pause\n"
        f"• /resume - Resume\n"
        f"• /skip - Skip\n"
        f"• /stop - Stop\n"
        f"• /queue - Show queue\n"
        f"• /join - Join voice chat\n"
        f"• /leave - Leave\n"
        f"• /ping - Check latency\n\n"
        f"{emoji(EMOJI['crown'], '👑')} <b>Made by:</b> @ZenoRealWebs",
        parse_mode="HTML"
    )

@app.on_message(filters.command("play") & filters.group)
async def play_command(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Check if user is in voice chat
    try:
        user = await app.get_chat_member(chat_id, user_id)
        if user.voice_chat is None:
            await message.reply_text(f"{emoji(EMOJI['stop'], '❌')} Join a voice chat first!", parse_mode="HTML")
            return
    except:
        await message.reply_text(f"{emoji(EMOJI['stop'], '❌')} Join a voice chat first!", parse_mode="HTML")
        return
    
    query = message.text.split(" ", 1)[1] if len(message.text.split()) > 1 else None
    if not query:
        await message.reply_text(f"{emoji(EMOJI['stop'], '❌')} Usage: /play <song name or URL>", parse_mode="HTML")
        return
    
    # Send loading message
    loading_msg = await message.reply_text(f"{emoji(EMOJI['loading'], '⏳')} Searching...", parse_mode="HTML")
    
    url, title, duration = await get_youtube_url(query)
    
    if not url:
        await loading_msg.edit_text(f"{emoji(EMOJI['stop'], '❌')} Could not find the song!")
        return
    
    # Check if already playing
    if chat_id in current_playing:
        if chat_id not in queues:
            queues[chat_id] = []
        queues[chat_id].append({'url': url, 'title': title, 'duration': duration})
        position = len(queues[chat_id])
        await loading_msg.edit_text(
            f"{emoji(EMOJI['check'], '✅')} <b>Added to queue!</b>\n\n"
            f"🎧 <b>{title}</b>\n"
            f"📍 Position: {position}\n"
            f"⏱️ Duration: {duration//60}:{duration%60:02d}",
            parse_mode="HTML"
        )
    else:
        await loading_msg.edit_text(f"{emoji(EMOJI['loading'], '⏳')} Downloading...", parse_mode="HTML")
        success = await play_song(chat_id, url, title, duration)
        if success:
            await loading_msg.delete()

@app.on_message(filters.command("pause") & filters.group)
async def pause_command(client, message):
    chat_id = message.chat.id
    await call.pause_stream(chat_id)
    await message.reply_text(f"{emoji(EMOJI['pause'], '⏸')} <b>Paused</b>", parse_mode="HTML")

@app.on_message(filters.command("resume") & filters.group)
async def resume_command(client, message):
    chat_id = message.chat.id
    await call.resume_stream(chat_id)
    await message.reply_text(f"{emoji(EMOJI['play'], '▶️')} <b>Resumed</b>", parse_mode="HTML")

@app.on_message(filters.command("skip") & filters.group)
async def skip_command(client, message):
    chat_id = message.chat.id
    if chat_id in current_playing:
        await play_next(chat_id)
        await message.reply_text(f"{emoji(EMOJI['skip'], '⏭')} <b>Skipped</b>", parse_mode="HTML")

@app.on_message(filters.command("stop") & filters.group)
async def stop_command(client, message):
    chat_id = message.chat.id
    if chat_id in queues:
        queues[chat_id].clear()
    current_playing.pop(chat_id, None)
    await call.leave_call(chat_id)
    await message.reply_text(f"{emoji(EMOJI['stop'], '🗑')} <b>Stopped and left</b>", parse_mode="HTML")

@app.on_message(filters.command("queue") & filters.group)
async def queue_command(client, message):
    chat_id = message.chat.id
    if chat_id not in queues or not queues[chat_id]:
        await message.reply_text(f"{emoji(EMOJI['queue'], '📜')} <b>Queue is empty!</b>", parse_mode="HTML")
        return
    
    queue_text = f"{emoji(EMOJI['queue'], '📜')} <b>Current Queue</b>\n\n"
    for i, song in enumerate(queues[chat_id][:10], 1):
        dur = song['duration']
        queue_text += f"{i}. {song['title']} [{dur//60}:{dur%60:02d}]\n"
    
    await message.reply_text(queue_text, parse_mode="HTML")

@app.on_message(filters.command("join") & filters.group)
async def join_command(client, message):
    chat_id = message.chat.id
    try:
        await call.join_call(chat_id)
        await message.reply_text(f"{emoji(EMOJI['check'], '✅')} <b>Joined voice chat!</b>", parse_mode="HTML")
    except Exception as e:
        await message.reply_text(f"{emoji(EMOJI['stop'], '❌')} Error: {e}", parse_mode="HTML")

@app.on_message(filters.command("leave") & filters.group)
async def leave_command(client, message):
    chat_id = message.chat.id
    try:
        await call.leave_call(chat_id)
        current_playing.pop(chat_id, None)
        if chat_id in queues:
            queues[chat_id].clear()
        await message.reply_text(f"{emoji(EMOJI['stop'], '👋')} <b>Left voice chat!</b>", parse_mode="HTML")
    except:
        await message.reply_text(f"{emoji(EMOJI['stop'], '❌')} Not in voice chat!", parse_mode="HTML")

@app.on_message(filters.command("ping") & filters.group)
async def ping_command(client, message):
    start = datetime.now()
    msg = await message.reply_text(f"{emoji(EMOJI['loading'], '🏓')} Pinging...", parse_mode="HTML")
    end = datetime.now()
    ping = (end - start).microseconds / 1000
    await msg.edit_text(f"{emoji(EMOJI['check'], '🏓')} <b>Pong!</b>\n\n📊 Latency: {ping:.2f}ms", parse_mode="HTML")

@app.on_message(filters.command("stats") & filters.user(OWNER_ID))
async def stats_command(client, message):
    total_users = await users_col.count_documents({})
    await message.reply_text(
        f"{emoji(EMOJI['crown'], '📊')} <b>Bot Statistics</b>\n\n"
        f"👥 Users: {total_users}\n"
        f"🎵 Active: {len(current_playing)}\n"
        f"📜 Queue: {sum(len(q) for q in queues.values())}",
        parse_mode="HTML"
    )

@app.on_callback_query()
async def callback_handler(client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    
    if data == "pause":
        await call.pause_stream(chat_id)
        await callback_query.answer("Paused")
    elif data == "resume":
        await call.resume_stream(chat_id)
        await callback_query.answer("Resumed")
    elif data == "skip":
        await play_next(chat_id)
        await callback_query.answer("Skipped")
    elif data == "stop":
        if chat_id in queues:
            queues[chat_id].clear()
        current_playing.pop(chat_id, None)
        await call.leave_call(chat_id)
        await callback_query.answer("Stopped")
    elif data == "queue":
        if chat_id not in queues or not queues[chat_id]:
            await callback_query.answer("Queue is empty!")
        else:
            await callback_query.answer(f"Queue: {len(queues.get(chat_id, []))} songs")
    elif data == "loop":
        loop_status[chat_id] = not loop_status.get(chat_id, False)
        await callback_query.answer(f"Loop: {'ON' if loop_status[chat_id] else 'OFF'}")

@call.on_stream_end()
async def on_stream_end(chat_id):
    if loop_status.get(chat_id, False) and chat_id in current_playing:
        song = current_playing[chat_id]
        await play_song(chat_id, song['url'], song['title'], song['duration'])
    else:
        await play_next(chat_id)

# ==================== RUN ====================
async def main():
    await user_client.start()
    await app.start()
    await call.start()
    print("🎵 Frozen Music Bot Started with Premium Emojis!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
