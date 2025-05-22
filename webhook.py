import os
import logging
import requests
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from fastapi import FastAPI, Request

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN or not WEBHOOK_URL:
    raise ValueError("BOT_TOKEN and WEBHOOK_URL must be set in environment variables")

app = FastAPI()
bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

# Book downloader logic
class eBookDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})

    def search_project_gutenberg(self, query, limit=10):
        try:
            response = self.session.get("https://gutendex.com/books/", params={'search': query, 'page_size': limit})
            return [{
                'id': str(b['id']),
                'title': b['title'],
                'author': ', '.join([a['name'] for a in b.get('authors', [])]),
                'source': 'gutenberg',
                'download_count': b.get('download_count', 0)
            } for b in response.json().get('results', [])]
        except Exception as e:
            logger.error(f"Gutenberg search error: {e}")
            return []

    def search_internet_archive(self, query, limit=5):
        try:
            response = self.session.get("https://archive.org/advancedsearch.php", params={
                'q': f'title:({query}) AND mediatype:texts',
                'fl': 'identifier,title,creator',
                'rows': limit,
                'output': 'json'
            })
            return [{
                'id': d.get('identifier', ''),
                'title': d.get('title', 'Unknown') if isinstance(d.get('title'), str) else d.get('title', ['Unknown'])[0],
                'author': d.get('creator', 'Unknown') if isinstance(d.get('creator'), str) else d.get('creator', ['Unknown'])[0],
                'source': 'archive'
            } for d in response.json().get('response', {}).get('docs', [])]
        except Exception as e:
            logger.error(f"Archive search error: {e}")
            return []

    def get_download_link(self, book_id, source):
        if source == 'gutenberg':
            return f"https://www.gutenberg.org/ebooks/{book_id}.epub.images"
        if source == 'archive':
            return f"https://archive.org/download/{book_id}/{book_id}.pdf"
        return None

downloader = eBookDownloader()
book_cache = {}
cache_counter = 0

# Bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /search <book> to find a book.")

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global cache_counter
    if not context.args:
        await update.message.reply_text("Usage: /search <book title>")
        return

    query = ' '.join(context.args)
    msg = await update.message.reply_text(f"🔍 Searching for *{query}*...", parse_mode="Markdown")

    books = downloader.search_project_gutenberg(query) + downloader.search_internet_archive(query)
    if not books:
        await msg.edit_text("❌ No results found.")
        return

    books.sort(key=lambda b: b.get("download_count", 0), reverse=True)
    keyboard = []
    for book in books[:12]:
        key = f"book_{cache_counter}"
        book_cache[key] = {'source': book['source'], 'id': book['id']}
        cache_counter += 1
        title = book['title'][:40]
        keyboard.append([InlineKeyboardButton(f"{book['source'].capitalize()}: {title}", callback_data=key)])

    await msg.edit_text(f"📚 Results for *{query}*:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = book_cache.get(query.data)
    if not data:
        await query.edit_message_text("❌ Invalid or expired selection.")
        return
    link = downloader.get_download_link(data['id'], data['source'])
    if link:
        await query.edit_message_text(f"[📥 Download your book here]({link})", parse_mode="Markdown", disable_web_page_preview=True)
        del book_cache[query.data]
    else:
        await query.edit_message_text("❌ Could not generate download link.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /search <book title> to find books.")

# Register handlers
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("search", search_books))
bot_app.add_handler(CallbackQueryHandler(handle_download, pattern="^book_"))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

@app.on_event("startup")
async def on_startup():
    await bot_app.initialize()
    await bot_app.bot.set_webhook(WEBHOOK_URL)
    await bot_app.start()

@app.post("/")
async def receive_update(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}
