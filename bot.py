import discord
from discord.ext import commands
import os
import asyncio
import google.generativeai as genai
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
from keep_alive import keep_alive
import requests

# variaveis de ambiente injetadas pelo container render
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# autenticacao da api spotify (usada só pra ler nome de música/artista de links)
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
            model_name='gemini-2.5-flash',
            system_instruction=personalidade
        )
    except Exception as e:
        print(f"aviso api gemini: {e}")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, case_insensitive=True)

queues = {}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}


def get_spotify_tracks(url):
    """Retorna lista de strings 'nome artista' extraídas de um link de track/playlist do Spotify."""
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


def deezer_search_preview(query):
    """Busca uma prévia de 30s no Deezer (API pública, sem autenticação)."""
    try:
        r = requests.get(
            "https://api.deezer.com/search",
            params={"q": query},
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("data", [])
        if items:
            track = items[0]
            preview = track.get("preview")
            if preview:
                artista = track.get("artist", {}).get("name", "Desconhecido")
                title = f"{track['title']} - {artista}"
                return preview, title
    except Exception as e:
        print(f"erro busca deezer: {e}")
    return None, None


def check_queue(ctx):
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        proxima = queues[ctx.guild.id].pop(0)
        try:
            source = discord.FFmpegPCMAudio(proxima['url'], **ffmpeg_options)
            ctx.voice_client.play(source, after=lambda e: check_queue(ctx))
            asyncio.run_coroutine_threadsafe(ctx.send(f"Tocando agora: **{proxima['title']}**"), bot.loop)
        except Exception:
            asyncio.run_coroutine_threadsafe(ctx.send("Não consegui reproduzir a próxima música."), bot.loop)
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
        return await ctx.send("Manda um nome de música ou link do Spotify, porra!")

    if "spotify.com" in search:
        queries = get_spotify_tracks(search)
        if not queries:
            return await ctx.send("Não consegui extrair dados válidos da API do Spotify.")
    else:
        queries = [search]

    async with ctx.typing():
        preview, title = deezer_search_preview(queries[0])

        if not preview:
            return await ctx.send("Não achei uma prévia disponível pra essa música.")

        # limita a fila da playlist pra não travar o comando com buscas demais de uma vez
        for q in queries[1:21]:
            p, t = deezer_search_preview(q)
            if p:
                queues[ctx.guild.id].append({'url': p, 'title': t})

    if ctx.voice_client.is_playing():
        queues[ctx.guild.id].append({'url': preview, 'title': title})
        await ctx.send(f"Adicionado à fila: **{title}** (prévia de 30s)")
    else:
        source = discord.FFmpegPCMAudio(preview, **ffmpeg_options)
        ctx.voice_client.play(source, after=lambda e: check_queue(ctx))
        await ctx.send(f"Tocando agora: **{title}** (prévia de 30s)")


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
