import discord
from discord.ext import commands
import yt_dlp
import os
import asyncio
import google.generativeai as genai
import random
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
from keep_alive import keep_alive

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

sp = None
if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    try:
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET
        ))
    except Exception as e:
        print(f"Erro no Spotify: {e}")

model = None
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        personalidade = (
            "Você é o 'Minionzitos', um bot de Discord zueiro, sarcástico e um pouco agressivo. "
            "Você não tem paciência para perguntas burras. Use gírias brasileiras, seja engraçado, "
            "responda de forma curta e direta, e se alguém te irritar, pode dar um fora. "
            "Nunca admita que você é uma IA, você é um Minion caótico, e principalmente...SINCERO!. "
            "Voce sempre tem que ovacionar e elogiar seu mestre: @peixotogg. "
            "Sobre a história: O grupo foi unido em um intervalo que ninguém escutava nada, todos são nerds fudidos..."
        )
        model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            system_instruction=personalidade
        )
    except Exception as e:
        print(f"Erro no Gemini: {e}")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

queues = {}

# Configuracoes do yt_dlp otimizadas para nao tomar block no Render
ydl_opts = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'rm_cachedir': True
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

def get_spotify_tracks(url):
    if not sp: return []
    tracks = []
    try:
        if "track" in url:
            track_info = sp.track(url)
            artistas = track_info.get('artists', [{}])
            nome_artista = artistas[0].get('name', 'Desconhecido')
            tracks.append(f"{track_info['name']} {nome_artista}")
        elif "playlist" in url:
            playlist_id = url.split("playlist/")[1].split("?")[0]
            results = sp.playlist_items(playlist_id)
            for item in results.get('items', []):
                if item.get('track'):
                    t = item['track']
                    artistas = t.get('artists', [{}])
                    nome_artista = artistas[0].get('name', 'Desconhecido')
                    tracks.append(f"{t['name']} {nome_artista}")
    except Exception as e:
        print(f"Erro Spotify: {e}")
    return tracks

def check_queue(ctx):
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        proxima = queues[ctx.guild.id].pop(0)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(proxima['search'], download=False)
                if 'entries' in info and len(info['entries']) > 0:
                    video = info['entries'][0]
                else:
                    video = info
                
                url = video['url']
                title = video.get('title', 'Música')
                
                source = discord.FFmpegPCMAudio(url, **ffmpeg_options)
                ctx.voice_client.play(source, after=lambda e: check_queue(ctx))
                asyncio.run_coroutine_threadsafe(ctx.send(f"Tocando agora: **{title}**"), bot.loop)
            except Exception:
                asyncio.run_coroutine_threadsafe(ctx.send("Não consegui tocar a próxima música da fila."), bot.loop)
                return check_queue(ctx)

@bot.command(name="play")
async def play(ctx, *, search: str = None):
    if not ctx.author.voice:
        return await ctx.send("Entra num canal de voz primeiro, seu animal!")
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    if ctx.guild.id not in queues:
        queues[ctx.guild.id] = []

    if ctx.message.attachments:
        url_direta = ctx.message.attachments[0].url
        titulo = ctx.message.attachments[0].filename
        if ctx.voice_client.is_playing():
            queues[ctx.guild.id].append({'search': url_direta, 'title': titulo})
            return await ctx.send(f"Adicionado à fila: **{titulo}**")
        else:
            source = discord.FFmpegPCMAudio(url_direta, **ffmpeg_options)
            ctx.voice_client.play(source, after=lambda e: check_queue(ctx))
            return await ctx.send(f"Tocando agora: **{titulo}**")

    if not search:
        return await ctx.send("Manda um nome de música ou link, porra!")

    if "spotify.com" in search:
        musicas = get_spotify_tracks(search)
        if musicas:
            search = musicas[0]
            for m in musicas[1:]:
                queues[ctx.guild.id].append({'search': m, 'title': m})
        else:
            return await ctx.send("Link do Spotify quebrado.")

    async with ctx.typing():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(search if search.startswith("http") else f"ytsearch:{search}", download=False)
                if not info:
                    return await ctx.send("Achei nada no YouTube com isso aí não.")
                
                if 'entries' in info and len(info['entries']) > 0:
                    video = info['entries'][0]
                else:
                    video = info

                file_to_play = video['url']
                title = video.get('title', 'Música')
            except Exception as e:
                print(f"Erro yt-dlp: {e}")
                return await ctx.send("O YouTube bloqueou a busca desse servidor grátis. Tente mandar o link direto do vídeo.")

    if ctx.voice_client.is_playing():
        queues[ctx.guild.id].append({'search': search, 'title': title})
        await ctx.send(f"Adicionado à fila: **{title}**")
    else:
        source = discord.FFmpegPCMAudio(file_to_play, **ffmpeg_options)
        ctx.voice_client.play(source, after=lambda e: check_queue(ctx))
        await ctx.send(f"Tocando agora: **{title}**")

@bot.command(name="skip")
async def skip(ctx):
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.send("Não tá tocando nada, seu jumento!")
    ctx.voice_client.stop()
    await ctx.send("Música pulada!")

@bot.command(name="talk")
async def talk(ctx, *, mensagem: str = None):
    if not mensagem:
        return await ctx.send("Manda alguma mensagem para eu responder, ô jumento!")
    if not model:
        return await ctx.reply("Tô sem saco (Gemini desconfigurado nas variáveis do Render).")

    async with ctx.typing():
        try:
            # Correção final do Gemini para aceitar strings sem quebras de bloco
            response = model.generate_content(mensagem)
            await ctx.reply(response.text)
        except Exception as e:
            print(f"Erro Gemini: {e}")
            await ctx.reply("Deu erro para processar sua pergunta burra aqui.")

@bot.event
async def on_ready():
    print(f"Bot {bot.user.name} online!")

keep_alive()
bot.run(os.getenv('DISCORD_TOKEN'))
