#!/usr/bin/env python3
"""
Bot de Cursos — Telegram
Corre no Railway (cloud, independente do Mac)

Variáveis de ambiente necessárias no Railway:
  TELEGRAM_TOKEN
  SUPABASE_URL
  SUPABASE_KEY
  ANTHROPIC_KEY
"""

import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client
from fastembed import TextEmbedding
import anthropic

logging.basicConfig(level=logging.INFO)

# ─── CREDENCIAIS (via Railway env vars) ──────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_KEY"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_KEY"]
# ─────────────────────────────────────────────────────────────────────────────

print("A carregar modelos...")
embed_model = TextEmbedding("BAAI/bge-small-en-v1.5")
supa        = create_client(SUPABASE_URL, SUPABASE_KEY)
claude      = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
print("✅ Pronto!")

def fmt_time(seconds):
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Bot de Cursos*\n\n"
        "Faz qualquer pergunta sobre o conteúdo dos teus vídeos.\n\n"
        "Exemplos:\n"
        "• _O que o Hormozi diz sobre pricing?_\n"
        "• _Como criar um hook eficaz?_\n"
        "• _Melhores estratégias para escalar uma app?_\n\n"
        "Digo-te exactamente em qual vídeo e a que minuto encontras a resposta.",
        parse_mode="Markdown"
    )

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    r = supa.table("transcricoes").select("video_nome", count="exact").execute()
    videos = len(set(row["video_nome"] for row in r.data)) if r.data else 0
    segs   = r.count or 0
    await update.message.reply_text(
        f"📊 *Base de conhecimento*\n\n"
        f"🎬 Vídeos indexados: {videos}\n"
        f"📝 Segmentos: {segs:,}",
        parse_mode="Markdown"
    )

async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    question = update.message.text
    msg = await update.message.reply_text("🔍 A pesquisar na base de conhecimento...")

    try:
        # Gerar embedding da pergunta
        q_emb = list(embed_model.embed([question]))[0].tolist()

        # Pesquisar no Supabase
        result = supa.rpc("buscar_segmentos", {
            "query_embedding": q_emb,
            "match_count": 10
        }).execute()

        if not result.data:
            await msg.edit_text(
                "Não encontrei conteúdo relevante ainda.\n"
                "Certifica-te que já indexaste alguns vídeos."
            )
            return

        # Montar contexto para o Claude
        context = ""
        seen = set()
        for r in result.data:
            key = f"{r['video_nome']}_{r['start_time']}"
            if key in seen: continue
            seen.add(key)
            start = fmt_time(r["start_time"])
            end   = fmt_time(r["end_time"])
            context += f"[{r['video_nome']} — {start} → {end}]\n{r['texto']}\n\n"

        # Pedir resposta ao Claude
        await msg.edit_text("🧠 A formular resposta...")
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content":
                f"""És um assistente que ajuda a aprender com base em transcrições de vídeos de cursos.

PERGUNTA: {question}

EXCERTOS RELEVANTES DOS VÍDEOS:
{context}

Responde de forma directa, prática e em português.
Sintetiza o que os vídeos dizem sobre o tema.
No final, indica SEMPRE os vídeos e timestamps relevantes neste formato exacto:

📍 nome_do_video.mp4 — MM:SS → MM:SS"""
            }]
        )

        await msg.edit_text(response.content[0].text)

    except Exception as e:
        await msg.edit_text(f"❌ Erro: {str(e)[:300]}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("🤖 Bot activo!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
