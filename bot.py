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

# variaveis de ambiente injetadas pelo container render
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# autenticacao da api spotify
sp = None
if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    try:
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET
        ))
    except Exception as e:
        print(f"aviso api spotify: {e}")

# autenticacao do LLM google gemini
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
        print(f"aviso api gemini: {e}")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

queues = {}

# parametros de encapsulamento para evitar evasao de ip (anti-bot bypass)
ydl_opts = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'source_address': '0.0.0.0',
    'extractor_args': {'youtube': {'player_client': ['android', 'ios']}}
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

def get_spotify_tracks(url):
    if not sp: 
        return []
    tracks = []
    try:
        if "track" in url:
            track_info = sp.track(url)
            artists = track_info.get('artists', [])
            artist_name = artists[0]['name'] if artists else "Desconhecido"
            tracks.append(f"{track_info['name']} {artist_name}")
        elif "playlist" in url:
            match = re.search(r"playlist/([^?]+)", url)
            if match:
                playlist_id = match.group(1)
                results = sp.playlist_items(playlist_id)
                for item in results.get('items', []):
                    if item.get('track'):
                        t = item['track']
                        artists = t.get('artists', [])
                        artist_name = artists[0]['name'] if artists else "Desconhecido"
                        tracks.append(f"{t['name']} {artist_name}")
    except Exception as e:
        print(f"erro parser spotify: {e}")
    return tracks

def check_queue(ctx):
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        proxima = queues[ctx.guild.id].pop(0)
        busca = proxima['url']
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                query = busca if (busca.startswith("http://") or busca.startswith("https://")) else f"ytsearch:{busca}"
                info = ydl.extract_info(query, download=False)
                
                if info and 'entries' in info and len(info['entries']) > 0:
                    video = info['entries'][0]
                else:
                    video = info

                if video and 'url' in video:
                    source = discord.FFmpegPCMAudio(video['url'], **ffmpeg_options)
                    ctx.voice_client.play(source, after=lambda e: check_queue(ctx))
                    asyncio.run_coroutine_threadsafe(ctx.send(f"Tocando agora: **{video.get('title', 'Música')}**"), bot.loop)
                else:
                    raise Exception()
            except Exception:
                asyncio.run_coroutine_threadsafe(ctx.send(f"Não consegui reproduzir a próxima música."), bot.loop)
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
            queues[ctx.guild.id].append({'url': url_direta, 'title': titulo})
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
                queues[ctx.guild.id].append({'url': m, 'title': m})
        else:
            return await ctx.send("Não consegui extrair dados válidos da API do Spotify.")

    async with ctx.typing():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                is_url = search.startswith("http://") or search.startswith("https://")
                query = search if is_url else f"ytsearch:{search}"
                info = ydl.extract_info(query, download=False)
                
                if not info:
                    return await ctx.send("Achei nada no YouTube com isso aí não.")
                
                if 'entries' in info and len(info['entries']) > 0:
                    video = info['entries'][0]
                else:
                    video = info

                file_to_play = video.get('url')
                title = video.get('title', 'Música')
            except Exception as e:
                print(f"excecao yt-dlp: {e}")
                return await ctx.send("O YouTube bloqueou a busca desse servidor grátis. Tente mandar o link direto do vídeo.")

    if not file_to_play:
        return await ctx.send("Falha na alocação de buffer do fluxo de áudio.")

    if ctx.voice_client.is_playing():
        queues[ctx.guild.id].append({'url': file_to_play, 'title': title})
        await ctx.send(f"Adicionado à fila: **{title}**")
    else:
        source = discord.FFmpegPCMAudio(file_to_play, **ffmpeg_options)
        ctx.voice_client.play(source, after=lambda e: check_queue(ctx))
        await ctx.send(f"Tocando agora: **{title}**")

@bot.command(name="skip")
async def skip(ctx):
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.send("Não há fluxos ativos em reprodução no momento.")
    ctx.voice_client.stop()
    await ctx.send("Música pulada!")

@bot.command(name="talk")
async def talk(ctx, *, mensagem: str = None):
    if not mensagem:
        return await ctx.send("O parâmetro textual obrigatório está ausente na chamada do comando.")
    if not model:
        return await ctx.reply("A instância LLM Gemini não pôde ser inicializada localmente.")

    async with ctx.typing():
        try:
            prompt_limpo = str(mensagem).replace('\\', '').strip()
            response = model.generate_content(prompt_limpo)
            if response and response.text:
                await ctx.reply(response.text)
            else:
                raise Exception()
        except Exception as e:
            print(f"excecao chamada gemini: {e}")
            await ctx.reply("Deu erro para processar sua pergunta burra aqui.")

@bot.event
async def on_ready():
    print(f"Instância de gateway ativa. Sincronizado como {bot.user.name}.")

keep_alive()
bot.run(os.getenv('DISCORD_TOKEN'))
