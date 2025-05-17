import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Admin user ID (add your Telegram numeric ID here or set in env variable)
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

def is_admin(user_id):
    return user_id == ADMIN_ID

# Dynamic welcome message (can be edited by admin)
welcome_message = "📚 Welcome to the Public Domain eBook Bot!\nSend me a book name to search in Project Gutenberg."

# Search Gutenberg API
def search_gutenberg(query):
    url = f"https://gutendex.com/books?search={query}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        books = data.get("results", [])
        return books[:3]
    return []

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(welcome_message)

# Search book (anyone can use)
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
            await update.message.reply_text(
                f"📖 *{title}*\n👤 {authors}\n🔗 [Download Here]({link})",
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        else:
            await update.message.reply_text(
                f"📖 *{title}*\n👤 {authors}\n❌ No download link found."
            )

# /stats admin command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    await update.message.reply_text("📊 Bot is running smoothly. No user data tracking enabled.")

# /editbot admin command - edit welcome message
async def editbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    global welcome_message
    new_msg = " ".join(context.args)
    if not new_msg:
        await update.message.reply_text("✏️ Usage: /editbot Your new welcome message")
        return

    welcome_message = new_msg
    await update.message.reply_text("✅ Welcome message updated.")

# Main bot setup
TOKEN = os.environ.get("BOT_TOKEN")
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("editbot", editbot))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))

print("✅ Bot running with admin commands...")
app.run_polling()
