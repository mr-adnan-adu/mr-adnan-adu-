import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ.get("BOT_TOKEN")

# Search Gutenberg
def search_gutenberg(query):
    url = f"https://gutendex.com/books?search={query}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        books = data.get("results", [])
        return books[:3]  # return top 3
    return []

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 Welcome to the Public Domain eBook Bot!\nSend me a book name to search in Project Gutenberg.")

# Book search
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    books = search_gutenberg(query)

    if not books:
        await update.message.reply_text("❌ No books found.")
        return

    for book in books:
        title = book["title"]
        authors = ", ".join([a["name"] for a in book["authors"]])
        link = book["formats"].get("application/pdf") or book["formats"].get("text/html")

        if link:
            await update.message.reply_text(f"📖 *{title}*\n👤 {authors}\n🔗 [Download Here]({link})", parse_mode="Markdown", disable_web_page_preview=True)
        else:
            await update.message.reply_text(f"📖 *{title}*\n👤 {authors}\n❌ No download link found.")

# Bot setup
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))

print("✅ Legal Bot running...")
app.run_polling()
