import os
import re
import discord
from discord.ext import tasks
import discord.app_commands

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
CHANNEL_ID = 1420795090259148810
LOG_FILE = r"C:\Users\[username]\Documents\Euro Truck Simulator 2\server.log.txt"
POLL_INTERVAL = 2  # 秒

intents = discord.Intents.all()
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

last_pos = 0
connected_players = set()
current_player_count = 0

RE_CONNECTED = re.compile(r"\[MP\]\s+(.+?)\s+connected\s*,\s*client_id", re.IGNORECASE)
RE_DISCONNECTED = re.compile(r"\[MP\]\s+(.+?)\s+disconnected\s*,\s*client_id", re.IGNORECASE)

async def get_channel():
    ch = client.get_channel(CHANNEL_ID)
    if ch is None:
        try:
            ch = await client.fetch_channel(CHANNEL_ID)
        except Exception:
            ch = None
    return ch

async def update_discord_status():
    global current_player_count
    ch = await get_channel()
    if ch is None:
        return

    player_count = len(connected_players)
    if player_count == current_player_count:
        return
    current_player_count = player_count

    try:
        await client.change_presence(
            status=discord.Status.online,
            activity=discord.CustomActivity(name=f"サーバー稼働中 | {player_count}人参加中")
        )
    except Exception as e:
        print("Failed to update bot presence:", e)

    try:
        old_topic = ch.topic or ""
        if "現在の参加人数：" in old_topic:
            new_topic = re.sub(r"現在の参加人数：\d+人", f"現在の参加人数：{player_count}人", old_topic)
        else:
            new_topic = f"{old_topic} | 現在の参加人数：{player_count}人" if old_topic else f"現在の参加人数：{player_count}人"
        await ch.edit(topic=new_topic)
    except Exception as e:
        print("Failed to update channel topic:", e)

def initialize_connected_players():
    global connected_players
    if not os.path.exists(LOG_FILE):
        return
    seen_clients = {}
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                m_conn = RE_CONNECTED.search(line)
                m_disc = RE_DISCONNECTED.search(line)
                if m_conn:
                    player = m_conn.group(1).strip()
                    client_id = line.split("client_id =")[-1].strip()
                    seen_clients[client_id] = player
                if m_disc:
                    client_id = line.split("client_id =")[-1].strip()
                    if client_id in seen_clients:
                        del seen_clients[client_id]
        connected_players = set(seen_clients.values())
        print(f"初期接続中プレイヤー: {connected_players}")
    except Exception as e:
        print("Failed to initialize connected players:", e)

@client.event
async def on_ready():
    global last_pos
    print(f"Logged in as {client.user} (id: {client.user.id})")
    await tree.sync()

    initialize_connected_players()
    await update_discord_status()

    last_pos = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0

    ch = await get_channel()
    if ch:
        await ch.send("`-ENJOYTRUCKERSコンボイサーバー管理システム-起動しました`")

    if not check_log.is_running():
        check_log.start()

@tasks.loop(seconds=POLL_INTERVAL)
async def check_log():
    global last_pos, connected_players

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            f.seek(last_pos)
            new_lines = f.readlines()
            last_pos = f.tell()
    except Exception as e:
        print("Error reading log file:", e)
        return

    if not new_lines:
        return

    ch = await get_channel()

    for line in new_lines:
        line = line.strip()
        if not line:
            continue

        m_conn = RE_CONNECTED.search(line)
        if m_conn:
            player = m_conn.group(1).strip()
            if player not in connected_players:
                connected_players.add(player)
                msg = f"🚛 **{player}** さんが参加しました。 現在の参加人数：{len(connected_players)}人"
                print(msg)
                if ch: await ch.send(msg)
                await update_discord_status()

        m_disc = RE_DISCONNECTED.search(line)
        if m_disc:
            player = m_disc.group(1).strip()
            if player in connected_players:
                connected_players.discard(player)
                msg = f"🚚 **{player}** さんが退出しました。 現在の参加人数：{len(connected_players)}人"
            else:
                msg = f"🚚 **{player}** さんが退出しました（未記録）。 現在の参加人数：{len(connected_players)}人"
            print(msg)
            if ch: await ch.send(msg)
            await update_discord_status()

@tree.command(name="now", description="現在の参加者情報を表示します")
async def now_players(interaction: discord.Interaction):
    if connected_players:
        sorted_list = sorted(connected_players)
        player_text = "\n".join(f"- {p}" for p in sorted_list)
        await interaction.response.send_message(f"👥 現在の接続人数：**{len(connected_players)}人**\n{player_text}")
    else:
        await interaction.response.send_message("👥 現在接続中のプレイヤーはいません。")

client.run(TOKEN)
