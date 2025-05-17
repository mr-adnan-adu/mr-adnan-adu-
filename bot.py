from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext
from telegram.error import BadRequest
import requests

BOT_TOKEN = "5681235797:AAG1aNjC-FgDE5Zws1Z-t_4pGGkBN0yh6yM"
ADMIN_ID = 1980071557
CHANNEL_USERNAME = "@AiTechWave"

users = set()

def is_subscribed(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    try:
        member = context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'creator', 'administrator']
    except BadRequest:
        return False

def restricted(func):
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if not is_subscribed(update, context):
            update.message.reply_text(f"ദയവായി ഞങ്ങളുടെ ചാനലിൽ ചേരുക {CHANNEL_USERNAME} ബോട്ട് ഉപയോഗിക്കാനായി.")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

def admin_only(func):
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if update.effective_user.id != ADMIN_ID:
            update.message.reply_text("ക്ഷമിക്കണം, ഈ കമാൻഡ് നിങ്ങൾക്ക് അനുവദനീയമല്ല.")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

@restricted
def start(update: Update, context: CallbackContext):
    users.add(update.effective_user.id)
    update.message.reply_text("സ്വാഗതം! /search <പുസ്തക നാമം> ഉപയോഗിച്ച് പുസ്തകങ്ങൾ Anna's Archive ൽ തിരയാം.")

@restricted
def search(update: Update, context: CallbackContext):
    query = " ".join(context.args)
    if not query:
        update.message.reply_text("ദയവായി ഒരു പുസ്തക നാമം നൽകുക. ഉദാ: /search Python")
        return

    search_url = f"https://archive.org/advancedsearch.php?q={query.replace(' ', '+')}&fl[]=identifier&sort[]=downloads desc&rows=1&page=1&output=json"
    try:
        res = requests.get(search_url).json()
        docs = res.get("response", {}).get("docs", [])
        if not docs:
            update.message.reply_text("ക്ഷമിക്കണം, കണ്ടെത്തിയില്ല.")
            return
        identifier = docs[0]["identifier"]
        download_link = f"https://archive.org/download/{identifier}/{identifier}.pdf"
    except Exception as e:
        update.message.reply_text("Search സമയത്ത് പിശക് സംഭവിച്ചു. വീണ്ടും ശ്രമിക്കുക.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Download PDF 📥", url=download_link)]
    ])

    update.message.reply_text(
        f"‘{query}’ എന്ന പുസ്തകത്തിന്റെ ഡൗൺലോഡ് ലിങ്ക്:",
        reply_markup=keyboard
    )

@admin_only
def broadcast(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("പ്രചരിപ്പിക്കാൻ സന്ദേശം നൽകുക. ഉദാ: /broadcast Hello users!")
        return
    message = " ".join(context.args)
    count = 0
    for uid in users:
        try:
            context.bot.send_message(uid, f"📢 Admin Broadcast:

{message}")
            count += 1
        except:
            pass
    update.message.reply_text(f"പ്രചരിപ്പിച്ചത് {count} ഉപയോക്താക്കൾക്ക്.")

@admin_only
def stats(update: Update, context: CallbackContext):
    update.message.reply_text(f"മൊത്തം ഉപയോക്താക്കൾ: {len(users)}")

def about(update: Update, context: CallbackContext):
    text = (
        "📚 *Ebooks Downloader Bot*

"
        "Version: 1.0
"
        "Created by: Your Name
"
        "Anna's Library, archive.org പോലുള്ള സൈറ്റുകളിൽ നിന്നും ഇബുക്കുകൾ ഡൗൺലോഡ് ചെയ്യാം.

"
        "Commands:
"
        "/search <bookname> - പുസ്തകങ്ങൾ തിരയുക
"
        "/about - ബോട്ട് വിവരങ്ങൾ

"
        f"ചാനലിൽ ചേരുക: {CHANNEL_USERNAME}"
    )
    update.message.reply_text(text, parse_mode="Markdown")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("search", search))
    dp.add_handler(CommandHandler("broadcast", broadcast))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(CommandHandler("about", about))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
