import discord
from discord.ext import commands
import yt_dlp
import os
import asyncio
import google.generativeai as genai
import random
import collections
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
from keep_alive import keep_alive
import ctypes
import nacl.secret
try:
    if not discord.opus.is_loaded():
        discord.opus.load_opus()
except Exception as e:
    print(f"aviso ao carregar opus: {e}")
# configuracao do spotify puxando do render de forma segura
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

# configuracao do gemini puxando do render de forma segura
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_KEY, transport='rest')

personalidade = (
    "Você é o 'Minionzitos', um bot de Discord zueiro, sarcástico e um pouco agressivo. "
    "Você não tem paciência para perguntas burras. Use gírias brasileiras, seja engraçado, "
    "responda de forma corta e direta, e se alguém te irritar, pode dar um fora. "
    "Nunca admita que você é uma IA, você é um Minion caótico, e principalmente...SINCERO!. "
    "Voce sempre tem que ovacionar e elogiar seu mestre: @peixotogg. "
    "Sobre a história: O grupo foi unido em um intervalo que ninguém escutava nada, todos são nerds fudidos..."
)

model = genai.GenerativeModel(
    model_name='models/gemini-flash-latest',
    system_instruction=personalidade
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

queues = {}

ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'ignoreerrors': True,
    'default_search': 'ytsearch',
    'noplaylist': True
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

def get_spotify_tracks(url):
    # extrai musicas de links do spotify
    tracks = []
    try:
        if "track" in url:
            track_info = sp.track(url)
            track_name = f"{track_info['name']} - {track_info['artists'][0]['name']}"
            tracks.append(track_name)
        elif "playlist" in url:
            playlist_id = url.split("playlist/")[1].split("?")[0]
            results = sp.playlist_items(playlist_id)
            for item in results['items']:
                if item['track']:
                    track = item['track']
                    tracks.append(f"{track['name']} - {track['artists'][0]['name']}")
    except Exception as e:
        print(f"erro ao buscar no spotify: {e}")
    return tracks

def check_queue(ctx):
    # gerencia a fila de musicas
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        proxima = queues[ctx.guild.id].pop(0)
        if not proxima['url'].startswith("http"):
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch:{proxima['url']}", download=False)
                if info and 'entries' in info and len(info['entries']) > 0:
                    proxima['url'] = info['entries'][0]['url']
                    proxima['title'] = info['entries'][0]['title']
                else:
                    asyncio.run_coroutine_threadsafe(
                        ctx.send("Não achei essa porra no YouTube, pulando..."), bot.loop
                    )
                    return check_queue(ctx)
        
        source = discord.FFmpegPCMAudio(proxima['url'], **ffmpeg_options)
        ctx.voice_client.play(source, after=lambda e: check_queue(ctx))
        asyncio.run_coroutine_threadsafe(
            ctx.send(f"Tocando agora: **{proxima['title']}**"), bot.loop
        )

@bot.command(name="play")
async def play(ctx, *, search: str = None):
    # toca musica por nome link ou arquivo anexado
    if not ctx.author.voice:
        return await ctx.send("Entra num canal de voz primeiro, seu animal!")
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()
        
    if ctx.guild.id not in queues:
        queues[ctx.guild.id] = []
        
    file_to_play = None
    title = ""
    
    if ctx.message.attachments:
        file_to_play = ctx.message.attachments[0].url
        title = ctx.message.attachments[0].filename
    elif search and os.path.exists(os.path.join("temp", search)):
        file_to_play = os.path.join("temp", search)
        title = search
    elif search:
        if "spotify.com" in search:
            pass
        else:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch:{search}" if not search.startswith("http") else search, download=False)
                if not info:
                    return await ctx.send("Achei nada no YouTube com isso aí não.")
                if 'entries' in info and len(info['entries']) > 0:
                    info_entry = info['entries'][0]
                    file_to_play = info_entry['url']
                    title = info_entry['title']
                elif 'url' in info:
                    file_to_play = info['url']
                    title = info['title']
                else:
                    return await ctx.send("Manda um nome de música, um link ou anexa um arquivo de áudio, porra!")
                    
    if ctx.voice_client.is_playing():
        queues[ctx.guild.id].append({'url': file_to_play, 'title': title})
        await ctx.send(f"Adicionado à fila: **{title}**")
    else:
        source = discord.FFmpegPCMAudio(file_to_play, **ffmpeg_options)
        ctx.voice_client.play(source, after=lambda e: check_queue(ctx))
        await ctx.send(f"Tocando agora: **{title}**")

@bot.command(name="skip")
async def skip(ctx):
    # pula a musica atual
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.send("Não tá tocando nada, seu jumento! Quer que eu pule o silêncio?")
    ctx.voice_client.stop()
    await ctx.send("Música pulada com sucesso! Próxima da fila...")

@bot.command(name="talk")
async def talk(ctx, *, mensagem: str = None):
    # envia uma pergunta para a ia do gemini responder
    if not mensagem:
        return await ctx.send("Manda alguma mensagem para eu responder, ô jumento!")
    
    async with ctx.typing():
        try:
            response = model.generate_content(mensagem)
            await ctx.reply(response.text)
        except Exception as e:
            print(f"erro no gemini: {e}")
            await ctx.send("Deu erro para processar sua pergunta burra aqui.")

@bot.event
async def on_ready():
    # mostra logs quando o bot liga
    print(f"Bot {bot.user.name} está online com a fúria dos Minions!")

# inicia o servidor de monitoramento 24h
keep_alive()

# puxa o token do discord do render de forma segura
token = os.getenv('DISCORD_TOKEN')
bot.run(token)
