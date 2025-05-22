import os
import logging
import requests
import re
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import asyncio
from threading import Thread
import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
PORT = int(os.getenv('PORT', 8080))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

class eBookDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def search_project_gutenberg(self, query, limit=10):
        """Search Project Gutenberg for free books"""
        try:
            # Use Gutenberg API
            api_url = "https://gutendex.com/books/"
            params = {
                'search': query,
                'page_size': limit
            }
            
            response = self.session.get(api_url, params=params, timeout=10)
            if response.status_code != 200:
                return []
            
            data = response.json()
            books = []
            
            for book in data.get('results', []):
                books.append({
                    'id': str(book['id']),
                    'title': book['title'],
                    'author': ', '.join([author['name'] for author in book.get('authors', [])]),
                    'source': 'gutenberg',
                    'download_count': book.get('download_count', 0)
                })
            
            return books
        except Exception as e:
            logger.error(f"Error searching Project Gutenberg: {e}")
            return []
    
    def search_internet_archive(self, query, limit=5):
        """Search Internet Archive for free books"""
        try:
            search_url = "https://archive.org/advancedsearch.php"
            params = {
                'q': f'title:({query}) AND mediatype:texts',
                'fl': 'identifier,title,creator,description',
                'rows': limit,
                'page': 1,
                'output': 'json'
            }
            
            response = self.session.get(search_url, params=params, timeout=10)
            if response.status_code != 200:
                return []
            
            data = response.json()
            books = []
            
            for doc in data.get('response', {}).get('docs', []):
                books.append({
                    'id': doc.get('identifier', ''),
                    'title': doc.get('title', ['Unknown'])[0] if isinstance(doc.get('title'), list) else doc.get('title', 'Unknown'),
                    'author': doc.get('creator', ['Unknown'])[0] if isinstance(doc.get('creator'), list) else doc.get('creator', 'Unknown'),
                    'source': 'archive'
                })
            
            return books
        except Exception as e:
            logger.error(f"Error searching Internet Archive: {e}")
            return []
    
    def get_download_link(self, book_id, source):
        """Get download link for a book"""
        try:
            if source == 'gutenberg':
                # Project Gutenberg EPUB format
                return f"https://www.gutenberg.org/ebooks/{book_id}.epub.images"
            elif source == 'archive':
                # Internet Archive PDF format
                return f"https://archive.org/download/{book_id}/{book_id}.pdf"
            return None
        except Exception as e:
            logger.error(f"Error getting download link: {e}")
            return None

# Initialize downloader
downloader = eBookDownloader()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    welcome_text = """
📚 *Welcome to Free eBooks Downloader Bot!*

I help you find and download free eBooks from legal sources.

*Available Commands:*
- /search <book name> - Search for books
- /help - Show help information
- /about - About this bot

*Example:* `/search Pride and Prejudice`

*Sources:*
📖 Project Gutenberg (70,000+ free books)
📚 Internet Archive (millions of free books)

_Note: Only free and public domain books are provided._
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help information."""
    help_text = """
📖 *eBooks Downloader Bot Help*

*Commands:*
- `/start` - Start the bot
- `/search <book name>` - Search for books
- `/help` - Show this help
- `/about` - About this bot

*How to use:*
1️⃣ Use `/search` followed by the book title
2️⃣ Choose from the search results
3️⃣ Click download to get the book

*Supported formats:*
- EPUB (Project Gutenberg)
- PDF (Internet Archive)

*Note:* All books provided are free and legally available.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show information about the bot."""
    about_text = """
ℹ️ *About Free eBooks Downloader Bot*

This bot provides access to free and public domain books from:

📖 *Project Gutenberg*
- 70,000+ free eBooks
- Classic literature
- Public domain works

📚 *Internet Archive*
- Millions of free books
- Academic texts
- Historical documents

🔒 *Legal & Safe*
- Only public domain books
- No copyright infringement
- Free for everyone

Built with ❤️ for book lovers worldwide.
    """
    await update.message.reply_text(about_text, parse_mode='Markdown')

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for books."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a book title to search.\n\n*Example:* `/search Pride and Prejudice`",
            parse_mode='Markdown'
        )
        return
    
    query = ' '.join(context.args)
    search_msg = await update.message.reply_text(f"🔍 Searching for '*{query}*'...", parse_mode='Markdown')
    
    # Search multiple sources
    gutenberg_books = downloader.search_project_gutenberg(query, 8)
    archive_books = downloader.search_internet_archive(query, 4)
    
    all_books = gutenberg_books + archive_books
    
    if not all_books:
        await search_msg.edit_text("❌ No books found. Try a different search term or check spelling.")
        return
    
    # Sort by relevance (download count for Gutenberg)
    all_books.sort(key=lambda x: x.get('download_count', 0), reverse=True)
    
    # Create inline keyboard with results
    keyboard = []
    for i, book in enumerate(all_books[:12]):  # Limit to 12 results
        source_emoji = "📖" if book['source'] == 'gutenberg' else "📚"
        title = book['title'][:45] + "..." if len(book['title']) > 45 else book['title']
        author = book.get('author', 'Unknown')[:20] + "..." if len(book.get('author', 'Unknown')) > 20 else book.get('author', 'Unknown')
        
        button_text = f"{source_emoji} {title}\n👤 {author}"
        callback_data = f"download_{book['source']}_{book['id']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await search_msg.edit_text(
        f"📚 Found *{len(all_books)}* books for '*{query}*':\n\nTap a book to download:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def download_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle book download requests."""
    query = update.callback_query
    await query.answer()
    
    try:
        # Parse callback data
        parts = query.data.split('_', 2)
        if len(parts) != 3:
            await query.edit_message_text("❌ Invalid selection. Please search again.")
            return
            
        _, source, book_id = parts
        
        await query.edit_message_text("📥 Preparing your download link...")
        
        download_link = downloader.get_download_link(book_id, source)
        
        if download_link:
            source_name = "Project Gutenberg" if source == 'gutenberg' else "Internet Archive"
            file_format = "EPUB" if source == 'gutenberg' else "PDF"
            
            message = f"""
📖 *Book Ready for Download!*

📚 *Source:* {source_name}
📄 *Format:* {file_format}

🔗 [**Download Book**]({download_link})

💡 *Tip:* Right-click and "Save as" to download to your device.
            """
            
            # Add back button
            keyboard = [[InlineKeyboardButton("🔙 Search Again", callback_data="back_to_search")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message, 
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        else:
            await query.edit_message_text("❌ Sorry, couldn't generate download link for this book. Please try another one.")
    
    except Exception as e:
        logger.error(f"Error in download_book: {e}")
        await query.edit_message_text("❌ An error occurred. Please try again later.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle non-command messages."""
    text = update.message.text.lower()
    
    if any(keyword in text for keyword in ['search', 'find', 'book', 'download']):
        await update.message.reply_text(
            "To search for books, use: `/search <book title>`\n\n*Example:* `/search The Great Gatsby`",
            parse_mode='Markdown'
        )
    elif any(keyword in text for keyword in ['help', 'how', 'command']):
        await help_command(update, context)
    else:
        await update.message.reply_text(
            "👋 Hi! I'm your free eBooks downloader bot.\n\nUse `/help` to see all available commands or `/search` to find books!"
        )

# Keep the service alive (important for Render)
def keep_alive():
    """Keep the service alive by making periodic requests."""
    import time
    import threading
    
    def ping():
        while True:
            try:
                time.sleep(300)  # Sleep for 5 minutes
                # You can add a simple HTTP server here if needed
            except Exception as e:
                logger.error(f"Keep alive error: {e}")
    
    thread = threading.Thread(target=ping)
    thread.daemon = True
    thread.start()

def main():
    """Start the bot."""
    # Keep service alive
    keep_alive()
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("search", search_books))
    application.add_handler(CallbackQueryHandler(download_book, pattern="^download_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run the bot
    logger.info("Starting bot...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
