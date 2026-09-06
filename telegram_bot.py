#!/usr/bin/env python3
"""
Bot de Cursos — Telegram
Corre no Railway (sem dependências pesadas de ML)
"""

import os, logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client
import anthropic

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_KEY"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_KEY"]

supa   = create_client(SUPABASE_URL, SUPABASE_KEY)
claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

def fmt_time(seconds):
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Bot de Cursos*\n\n"
        "Faz qualquer pergunta sobre os teus vídeos.\n\n"
        "Exemplos:\n"
        "• _O que o Hormozi diz sobre pricing?_\n"
        "• _Como criar um hook eficaz?_\n"
        "• _Como escalar uma app mobile?_\n\n"
        "Digo-te exactamente em qual vídeo e a que minuto.",
        parse_mode="Markdown"
    )

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    r = supa.table("transcricoes").select("video_nome").execute()
    videos = len(set(row["video_nome"] for row in r.data)) if r.data else 0
    segs   = len(r.data) if r.data else 0
    await update.message.reply_text(
        f"📊 *Base de conhecimento*\n\n"
        f"🎬 Vídeos indexados: {videos}\n"
        f"📝 Segmentos: {segs:,}",
        parse_mode="Markdown"
    )

async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    question = update.message.text
    msg = await update.message.reply_text("🔍 A pesquisar...")

    try:
        # Passo 1: Claude extrai palavras-chave em inglês
        kw_resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=80,
            messages=[{"role": "user", "content":
                f"Extract 5-8 English search keywords from this question. "
                f"Return ONLY the keywords separated by spaces, nothing else: {question}"
            }]
        )
        keywords = kw_resp.content[0].text.strip()

        # Passo 2: Pesquisa full-text no Supabase
        result = supa.rpc("buscar_texto", {
            "query_text": keywords,
            "max_results": 12
        }).execute()

        # Fallback: se texto não encontrar, busca por ilike
        if not result.data:
            first_kw = keywords.split()[0] if keywords else question
            result = supa.table("transcricoes") \
                .select("video_nome, start_time, end_time, texto") \
                .ilike("texto", f"%{first_kw}%") \
                .limit(10) \
                .execute()

        if not result.data:
            await msg.edit_text(
                "Não encontrei conteúdo relevante ainda.\n"
                "Certifica-te que já indexaste alguns vídeos."
            )
            return

        # Passo 3: Montar contexto
        context = ""
        for r in result.data:
            start = fmt_time(r["start_time"])
            end   = fmt_time(r["end_time"])
            context += f"[{r['video_nome']} — {start} → {end}]\n{r['texto']}\n\n"

        # Passo 4: Claude sintetiza resposta
        await msg.edit_text("🧠 A formular resposta...")
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content":
                f"""És um assistente que ajuda a aprender com base em transcrições de vídeos de cursos.

PERGUNTA: {question}

EXCERTOS DOS VÍDEOS:
{context}

Responde em português de forma directa e prática.
Sintetiza o que os vídeos ensinam sobre o tema.
No final indica sempre os vídeos e timestamps relevantes no formato:
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
