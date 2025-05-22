from telegram.ext import ApplicationBuilder
from fastapi import FastAPI, Request
from telegram.ext import CommandHandler
import os

app = FastAPI()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

# Add your handlers
async def start(update, context):
    await update.message.reply_text("Hello! I’m your eBook bot 📚")

bot_app.add_handler(CommandHandler("start", start))

@app.on_event("startup")
async def on_startup():
    await bot_app.bot.set_webhook(url=WEBHOOK_URL)
    await bot_app.initialize()
    await bot_app.start()

@app.post("/")
async def telegram_webhook(req: Request):
    json_data = await req.json()
    await bot_app.update_queue.put(json_data)
    return {"ok": True}
