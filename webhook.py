import os
from fastapi import FastAPI, Request
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)
from telegram import Update

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app = FastAPI()
bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

# Example handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! I’m your eBooks bot. Use /search to find a book.")

bot_app.add_handler(CommandHandler("start", start))

@app.on_event("startup")
async def on_startup():
    await bot_app.initialize()
    await bot_app.bot.set_webhook(url=WEBHOOK_URL)
    await bot_app.start()

@app.post("/")
async def telegram_webhook(req: Request):
    data = await req.json()
    await bot_app.update_queue.put(data)
    return {"ok": True}
