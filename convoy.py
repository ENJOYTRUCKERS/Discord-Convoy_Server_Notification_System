import os
import re
import datetime
import asyncio
import discord
from discord.ext import tasks, commands
from typing import Optional, Set

class ConvoyBot(commands.Bot):
    """
    Euro Truck Simulator 2 コンボイサーバーのログを監視し、
    Discordに通知を行うボットクラス。
    """
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = False  # 必要に応じて変更
        intents.message_content = True
        
        super().__init__(command_prefix="!", intents=intents)
        
        # 環境変数から設定を取得
        self.token = os.environ.get("DISCORD_BOT_TOKEN")
        self.channel_id_raw = os.environ.get("DISCORD_CHANNEL_ID")
        self.log_file = os.environ.get("CONVOY_LOG_PATH", r"C:\Users\User\Documents\Euro Truck Simulator 2\server.log.txt")
        self.poll_interval = int(os.environ.get("POLL_INTERVAL", 2))
        
        self.channel_id = int(self.channel_id_raw) if self.channel_id_raw and self.channel_id_raw.isdigit() else None
        
        # 状態管理
        self.last_pos = 0
        self.connected_players: Set[str] = set()
        self.current_player_count = -1
        self.last_topic_update = datetime.datetime.min
        
        # 正規表現パターン
        self.RE_CONNECTED = re.compile(r"\[MP\]\s+(.+?)\s+connected\s*,\s*client_id", re.IGNORECASE)
        self.RE_DISCONNECTED = re.compile(r"\[MP\]\s+(.+?)\s+disconnected\s*,\s*client_id", re.IGNORECASE)

    async def setup_hook(self):
        """ボット起動時のセットアップ」"""
        # スラッシュコマンド同期
        await self.tree.sync()
        # ログ監視タスク開始
        self.check_log.start()

    async def on_ready(self):
        """ログイン完了時の処理"""
        print(f"Logged in as {self.user} (id: {self.user.id})")
        
        # 初期状態の設定
        self.initialize_connected_players()
        if os.path.exists(self.log_file):
            self.last_pos = os.path.getsize(self.log_file)
        else:
            print(f"Warning: Log file not found at {self.log_file}")
            self.last_pos = 0
            
        # 起動通知
        channel = self.get_convoy_channel()
        if channel:
            embed = discord.Embed(
                title="システム通知",
                description="✅ **ENJOYTRUCKERS コンボイ管理システムが起動しました**",
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now()
            )
            await channel.send(embed=embed)
            
        await self.update_discord_status(force=True)

    def get_convoy_channel(self) -> Optional[discord.TextChannel]:
        """通知対象のチャンネルオブジェクトを取得"""
        if not self.channel_id:
            return None
        return self.get_channel(self.channel_id)

    def initialize_connected_players(self):
        """ログファイルから現在の接続プレイヤーを初期化"""
        if not os.path.exists(self.log_file):
            return
            
        seen_clients = {}
        try:
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    m_conn = self.RE_CONNECTED.search(line)
                    m_disc = self.RE_DISCONNECTED.search(line)
                    if m_conn:
                        player = m_conn.group(1).strip()
                        # client_id をキーにして管理（初期化時のみ）
                        client_id_part = line.split("client_id =")[-1].strip() if "client_id =" in line else "unknown"
                        seen_clients[client_id_part] = player
                    if m_disc:
                        client_id_part = line.split("client_id =")[-1].strip() if "client_id =" in line else "unknown"
                        if client_id_part in seen_clients:
                            del seen_clients[client_id_part]
                            
            self.connected_players = set(seen_clients.values())
            print(f"初期接続プレイヤー: {list(self.connected_players)}")
        except Exception as e:
            print(f"Error during initialization: {e}")

    async def update_discord_status(self, force=False):
        """Discordのステータスとチャンネルトピックを更新"""
        player_count = len(self.connected_players)
        
        # 変化がない場合はスキップ（強制更新時を除く）
        if not force and player_count == self.current_player_count:
            return
            
        self.current_player_count = player_count
        
        # プレゼンス更新
        try:
            activity = discord.CustomActivity(name=f"🚚 サーバー稼働中 | {player_count}人参加中")
            await self.change_presence(status=discord.Status.online, activity=activity)
        except Exception as e:
            print(f"Presence update error: {e}")

        # チャンネルトピック更新（レート制限対応: 5分に1回程度に抑制）
        now = datetime.datetime.now()
        if force or (now - self.last_topic_update).total_seconds() > 300:
            channel = self.get_convoy_channel()
            if channel:
                try:
                    old_topic = channel.topic or ""
                    topic_text = f"現在の参加人数：{player_count}人"
                    
                    if "現在の参加人数：" in old_topic:
                        new_topic = re.sub(r"現在の参加人数：\d+人", topic_text, old_topic)
                    else:
                        new_topic = f"{old_topic} | {topic_text}" if old_topic else topic_text
                    
                    if new_topic != old_topic:
                        await channel.edit(topic=new_topic)
                        self.last_topic_update = now
                except Exception as e:
                    print(f"Topic update error: {e}")

    @tasks.loop(seconds=2)
    async def check_log(self):
        """ログファイルをポーリングして更新を検知"""
        if not os.path.exists(self.log_file):
            return

        current_size = os.path.getsize(self.log_file)
        
        # ファイルがリセットされた（切り詰められた）場合の対応
        if current_size < self.last_pos:
            self.last_pos = 0
            print("Log file rotated or reset. Restarting from beginning.")

        try:
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self.last_pos)
                new_lines = f.readlines()
                self.last_pos = f.tell()
        except Exception as e:
            print(f"Log read error: {e}")
            return

        if not new_lines:
            return

        channel = self.get_convoy_channel()
        for line in new_lines:
            line = line.strip()
            if not line:
                continue

            # Join
            m_conn = self.RE_CONNECTED.search(line)
            if m_conn:
                player = m_conn.group(1).strip()
                if player not in self.connected_players:
                    self.connected_players.add(player)
                    await self.send_notification(player, True, channel)
                    await self.update_discord_status()

            # Leave
            m_disc = self.RE_DISCONNECTED.search(line)
            if m_disc:
                player = m_disc.group(1).strip()
                if player in self.connected_players:
                    self.connected_players.discard(player)
                    await self.send_notification(player, False, channel)
                    await self.update_discord_status()

    async def send_notification(self, player: str, joined: bool, channel: Optional[discord.TextChannel]):
        """入退出通知を送信"""
        if not channel:
            return
            
        color = discord.Color.green() if joined else discord.Color.red()
        action = "参加しました" if joined else "退出しました"
        emoji = "🚛" if joined else "🚚"
        
        embed = discord.Embed(
            description=f"{emoji} **{player}** さんが{action}。",
            color=color,
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text=f"現在の参加人数: {len(self.connected_players)}人")
        
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"Notification send error: {e}")

    def run_bot(self):
        """ボットを起動"""
        if not self.token:
            print("Error: DISCORD_BOT_TOKEN environment variable is not set.")
            return
        self.run(self.token)

# --- Commands ---

bot = ConvoyBot()

@bot.tree.command(name="now", description="現在のコンボイ参加者一覧を表示します")
async def now_players(interaction: discord.Interaction):
    if bot.connected_players:
        sorted_list = sorted(bot.connected_players)
        player_text = "\n".join(f"- {p}" for p in sorted_list)
        embed = discord.Embed(
            title="👥 現在の参加者情報",
            description=f"合計: **{len(bot.connected_players)}人**\n\n{player_text}",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
    else:
        embed = discord.Embed(
            description="👥 現在、接続中のプレイヤーはいません。",
            color=discord.Color.light_grey()
        )
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    bot.run_bot()
