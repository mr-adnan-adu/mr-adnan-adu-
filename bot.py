from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.error import BadRequest
import requests
import logging

BOT_TOKEN = "5681235797:AAG1aNjC-FgDE5Zws1Z-t_4pGGkBN0yh6yM"
ADMIN_ID = 1980071557
CHANNEL_USERNAME = "AiTechWave"

users = set()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

async def is_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, update.effective_user.id)
        return member.status in ['member', 'creator', 'administrator']
    except BadRequest:
        return False

def restricted(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await is_subscribed(update, context):
            await update.message.reply_text(f"ദയവായി ഞങ്ങളുടെ ചാനലിൽ ചേരുക {CHANNEL_USERNAME} ബോട്ട് ഉപയോഗിക്കാനായി.")
            return
        return await func(update, context)
    return wrapper

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("ക്ഷമിക്കണം, ഈ കമാൻഡ് നിങ്ങൾക്ക് അനുവദനീയമല്ല.")
            return
        return await func(update, context)
    return wrapper

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users.add(update.effective_user.id)
    await update.message.reply_text("സ്വാഗതം! /search <പുസ്തക നാമം> ഉപയോഗിച്ച് പുസ്തകങ്ങൾ Anna's Archive ൽ തിരയാം.")

@restricted
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("ദയവായി ഒരു പുസ്തക നാമം നൽകുക. ഉദാ: /search Python")
        return

    search_url = f"https://archive.org/advancedsearch.php?q={query.replace(' ', '+')}&fl[]=identifier&sort[]=downloads desc&rows=1&page=1&output=json"
    try:
        res = requests.get(search_url).json()
        docs = res.get("response", {}).get("docs", [])
        if not docs:
            await update.message.reply_text("ക്ഷമിക്കണം, കണ്ടെത്തിയില്ല.")
            return
        identifier = docs[0]["identifier"]
        download_link = f"https://archive.org/download/{identifier}/{identifier}.pdf"
    except Exception as e:
        await update.message.reply_text("Search സമയത്ത് പിശക് സംഭവിച്ചു. വീണ്ടും ശ്രമിക്കുക.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Download PDF 📥", url=download_link)]
    ])

    await update.message.reply_text(
        f"‘{query}’ എന്ന പുസ്തകത്തിന്റെ ഡൗൺലോഡ് ലിങ്ക്:",
        reply_markup=keyboard
    )

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("പ്രചരിപ്പിക്കാൻ സന്ദേശം നൽകുക. ഉദാ: /broadcast Hello users!")
        return
    message = " ".join(context.args)
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(uid, f"📢 Admin Broadcast:\n{message}")
            count += 1
        except:
            pass
    await update.message.reply_text(f"പ്രചരിപ്പിച്ചത് {count} ഉപയോക്താക്കൾക്ക്.")

@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"മൊത്തം ഉപയോക്താക്കൾ: {len(users)}")

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 *Ebooks Downloader Bot*\n\n"
        "Version: 1.0\n"
        "Created by: Your Name\n"
        "Anna's Library, archive.org പോലുള്ള സൈറ്റുകളിൽ നിന്നും ഇബുക്കുകൾ ഡൗൺലോഡ് ചെയ്യാം.\n\n"
        "Commands:\n"
        "/search <bookname> - പുസ്തകങ്ങൾ തിരയുക\n"
        "/about - ബോട്ട് വിവരങ്ങൾ\n\n"
        f"ചാനലിൽ ചേരുക: {CHANNEL_USERNAME}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("about", about))

    print("Bot started…")
    app.run_polling()

if __name__ == "__main__":
    main()
