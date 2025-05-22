import os
import logging
import aiohttp
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from aiohttp import web
from threading import Thread
import time
from collections import defaultdict
from hashlib import md5
from typing import List, Optional
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import asyncio
import aiohttp.client_exceptions

# Configure logging with more detail
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
PORT = int(os.getenv('PORT', 8080))
BASE_URL = os.getenv('BASE_URL', 'https://your-bot-url.onrender.com')
ADMIN_IDS = os.getenv('ADMIN_IDS', '').split(',')
ADMIN_IDS = [int(admin_id) for admin_id in ADMIN_IDS if admin_id.isdigit()]
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
if not ADMIN_IDS:
    logger.warning("No ADMIN_IDS set; /broadcast command will be disabled")

# In-memory storage
book_cache = {}
search_cache = {}
cache_counter = 0
user_ids = set()

class BotStats:
    def __init__(self):
        self.start_time = datetime.now()
        self.search_count = 0
    
    def increment_searches(self):
        self.search_count += 1
    
    def get_uptime(self) -> str:
        uptime = datetime.now() - self.start_time
        days, seconds = uptime.days, uptime.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{days}d {hours}h {minutes}m"
    
    def get_stats(self) -> dict:
        return {
            'uptime': self.get_uptime(),
            'search_count': self.search_count,
            'cache_size': len(book_cache),
            'user_count': len(user_ids)
        }

bot_stats = BotStats()

class RateLimiter:
    def __init__(self, max_requests, time_window):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
    
    def is_allowed(self, user_id):
        current_time = time.time()
        self.requests[user_id] = [t for t in self.requests[user_id] if current_time - t < self.time_window]
        if len(self.requests[user_id]) >= self.max_requests:
            return False
        self.requests[user_id].append(current_time)
        return True
    
    def remaining_requests(self, user_id):
        current_time = time.time()
        self.requests[user_id] = [t for t in self.requests[user_id] if current_time - t < self.time_window]
        return max(0, self.max_requests - len(self.requests[user_id]))

rate_limiter = RateLimiter(max_requests=5, time_window=60)
broadcast_limiter = RateLimiter(max_requests=1, time_window=300)

class zLibrarySearch:
    def __init__(self):
        # Note: z-lib.is may change or be blocked; verify the current domain before deployment
        self.base_url = "https://z-lib.is"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.rate_limiter = RateLimiter(max_requests=5, time_window=60)
        
    async def search_books(self, query: str, limit: int = 10, page: int = 1) -> List[dict]:
        try:
            if not self.rate_limiter.is_allowed(hash(query)):
                logger.warning("Z-Library rate limit exceeded for query: %s", query)
                return []
            
            search_url = f"{self.base_url}/s/{quote(query)}"
            params = {'page': page} if page > 1 else {}
            response = await self._make_request(search_url, params)
            
            if not response:
                return []
                
            return await self._parse_search_results(response, limit)
            
        except Exception as e:
            logger.error(f"Z-Library search error for query '{query}': {e}")
            return []
            
    async def get_download_info(self, book_url: str) -> Optional[dict]:
        try:
            if not self.rate_limiter.is_allowed(hash(book_url)):
                logger.warning("Z-Library download rate limit exceeded for URL: %s", book_url)
                return None
                
            response = await self._make_request(book_url)
            if not response:
                return None
                
            return await self._parse_download_info(response)
            
        except Exception as e:
            logger.error(f"Z-Library download info error for URL '{book_url}': {e}")
            return None
            
    async def _make_request(self, url: str, params: dict = None) -> Optional[str]:
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        return await response.text()
                    logger.warning(f"Z-Library request to {url} failed with status {response.status}")
                    return None
                    
        except aiohttp.ClientError as e:
            logger.error(f"Z-Library request error for {url}: {e}")
            return None
            
    async def _parse_search_results(self, html_content: str, limit: int) -> List[dict]:
        books = []
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for item in soup.select('.resItemBox')[:limit]:
                try:
                    title_elem = item.select_one('.title')
                    author_elem = item.select_one('.authors')
                    year_elem = item.select_one('.property_year')
                    lang_elem = item.select_one('.property_language')
                    format_elem = item.select_one('.property_format')
                    size_elem = item.select_one('.property_size')
                    desc_elem = item.select_one('.description')
                    
                    book = {
                        'title': title_elem.text.strip() if title_elem else 'Unknown Title',
                        'author': author_elem.text.strip() if author_elem else 'Unknown Author',
                        'year': year_elem.text.strip() if year_elem else 'Unknown',
                        'language': lang_elem.text.strip() if lang_elem else 'Unknown',
                        'format': format_elem.text.strip() if format_elem else 'Unknown',
                        'file_size': size_elem.text.strip() if size_elem else 'Unknown',
                        'description': desc_elem.text.strip()[:200] + '...' if desc_elem and len(desc_elem.text.strip()) > 200 else desc_elem.text.strip() if desc_elem else 'No description available',
                        'url': self.base_url + title_elem['href'] if title_elem and title_elem.get('href') else None,
                        'source': 'zlibrary',
                        'isbn': None
                    }
                    books.append(book)
                except Exception as e:
                    logger.error(f"Z-Library parse error for item: {e}")
                    continue
        except Exception as e:
            logger.error(f"Z-Library parse results error: {e}")
        return books
        
    async def _parse_download_info(self, html_content: str) -> Optional[dict]:
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            info = {
                'formats': [],
                'size': None,
                'language': None,
                'isbn': None,
                'download_url': None,
                'description': None
            }
            
            format_elements = soup.select('.property_format')
            info['formats'] = [fmt.text.strip() for fmt in format_elements] or ['Unknown']
            
            size_elem = soup.select_one('.property_size')
            info['size'] = size_elem.text.strip() if size_elem else 'Unknown'
            
            lang_elem = soup.select_one('.property_language')
            info['language'] = lang_elem.text.strip() if lang_elem else 'Unknown'
            
            isbn_elem = soup.select_one('.property_isbn')
            info['isbn'] = isbn_elem.text.strip() if isbn_elem else 'Unknown'
            
            desc_elem = soup.select_one('.description')
            info['description'] = desc_elem.text.strip()[:500] + '...' if desc_elem and len(desc_elem.text.strip()) > 500 else desc_elem.text.strip() if desc_elem else 'No description available'
            
            download_elem = soup.select_one('a[href*="/dl/"]')
            if download_elem and download_elem.get('href'):
                info['download_url'] = self.base_url + download_elem['href']
                
            return info if info['formats'] or info['download_url'] else None
            
        except Exception as e:
            logger.error(f"Z-Library parse download info error: {e}")
            return None
    
    async def check_health(self) -> bool:
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(self.base_url, timeout=5) as response:
                    return response.status == 200
        except aiohttp.ClientError:
            return False

class eBookDownloader:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.zlibrary = zLibrarySearch()
    
    cache

    async def search_project_gutenberg(self, query, limit=10, page=1):
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(
                    "https://gutendex.com/books/",
                    params={'search': query, 'page_size': limit, 'page': page},
                    timeout=10
                ) as response:
                    if response.status != 200:
                        logger.warning(f"Gutenberg API returned status {response.status}")
                        return []
                    data = await response.json()
                    books = []
                    for book in data.get('results', []):
                        books.append({
                            'id': str(book['id']),
                            'title': book['title'],
                            'author': ', '.join([author['name'] for author in book.get('authors', [])]) or 'Unknown',
                            'year': str(book.get('copyright_year', 'Unknown')),
                            'language': book.get('languages', ['Unknown'])[0],
                            'format': 'EPUB',
                            'file_size': 'Approx. 500 KB',
                            'description': book.get('summary', 'No description available')[:200] + '...' if book.get('summary') and len(book.get('summary')) > 200 else book.get('summary', 'No description available'),
                            'source': 'gutenberg',
                            'download_count': book.get('download_count', 0),
                            'isbn': 'Unknown'
                        })
                    return books
        except aiohttp.ClientError as e:
            logger.error(f"Error searching Project Gutenberg: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in Gutenberg search: {e}")
            return []
    
    async def search_internet_archive(self, query, limit=5, page=1):
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(
                    "https://archive.org/advancedsearch.php",
                    params={
                        'q': f'title:({query}) AND mediatype:texts',
                        'fl': 'identifier,title,creator,description,language,format,size,isbn',
                        'rows': limit,
                        'page': page,
                        'output': 'json'
                    },
                    timeout=10
                ) as response:
                    if response.status != 200:
                        logger.warning(f"Internet Archive API returned status {response.status}")
                        return []
                    data = await response.json()
                    books = []
                    for doc in data.get('response', {}).get('docs', []):
                        title = doc.get('title', 'Unknown')
                        if isinstance(title, list):
                            title = title[0] if title else 'Unknown'
                        author = doc.get('creator', 'Unknown')
                        if isinstance(author, list):
                            author = author[0] if author else 'Unknown'
                        books.append({
                            'id': doc.get('identifier', ''),
                            'title': title,
                            'author': author,
                            'year': doc.get('year', 'Unknown'),
                            'language': doc.get('language', 'Unknown'),
                            'format': doc.get('format', 'PDF') or 'PDF',
                            'file_size': f"{int(doc.get('size', 0)) // 1024} KB" if doc.get('size') else 'Unknown',
                            'description': doc.get('description', 'No description available')[:200] + '...' if doc.get('description') and len(doc.get('description')) > 200 else doc.get('description', 'No description available'),
                            'source': 'archive',
                            'isbn': doc.get('isbn', 'Unknown')
                        })
                    return books
        except aiohttp.ClientError as e:
            logger.error(f"Error searching Internet Archive: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in Archive search: {e}")
            return []
    
    async def search_all_sources(self, query: str, limit: int = 10, page: int = 1) -> List[dict]:
        try:
            gutenberg_task = self.search_project_gutenberg(query, limit // 3, page)
            archive_task = self.search_internet_archive(query, limit // 3, page)
            zlibrary_task = self.zlibrary.search_books(query, limit // 3, page)
            results = await asyncio.gather(gutenberg_task, archive_task, zlibrary_task, return_exceptions=True)
            combined_results = []
            for result in results:
                if isinstance(result, list):
                    combined_results.extend(result)
                else:
                    logger.warning(f"Search task failed: {result}")
            return combined_results
        except Exception as e:
            logger.error(f"Error searching all sources: {e}")
            return []
    
    async def get_download_link(self, book_id: str, source: str) -> Optional[str]:
        try:
            if source == 'gutenberg':
                return f"https://www.gutenberg.org/ebooks/{book_id}.epub.images"
            elif source == 'archive':
                return f"https://archive.org/download/{book_id}/{book_id}.pdf"
            elif source == 'zlibrary':
                info = await self.zlibrary.get_download_info(book_id)
                if info and info.get('download_url'):
                    return info['download_url']
                return None
            return None
        except Exception as e:
            logger.error(f"Error getting download link for {source}/{book_id}: {e}")
            return None
    
    async def check_health(self) -> dict:
        async def check_gutenberg():
            try:
                async with aiohttp.ClientSession(headers=self.headers) as session:
                    async with session.get("https://gutendex.com/books/", timeout=5) as response:
                        return response.status == 200
            except aiohttp.ClientError:
                return False
        
        async def check_archive():
            try:
                async with aiohttp.ClientSession(headers=self.headers) as session:
                    async with session.get("https://archive.org/advancedsearch.php", timeout=5) as response:
                        return response.status == 200
            except aiohttp.ClientError:
                return False
        
        gutenberg, archive, zlibrary = await asyncio.gather(
            check_gutenberg(),
            check_archive(),
            self.zlibrary.check_health(),
            return_exceptions=True
        )
        return {
            'gutenberg': gutenberg if not isinstance(gutenberg, Exception) else False,
            'archive': archive if not isinstance(archive, Exception) else False,
            'zlibrary': zlibrary if not isinstance(zlibrary, Exception) else False
        }

# Initialize downloader
downloader = eBookDownloader()

def cleanup_cache():
    current_time = time.time()
    expired_books = [k for k, v in book_cache.items() if current_time - v['timestamp'] > 3600]
    for k in expired_books:
        book_cache.pop(k, None)
    expired_searches = [k for k, v in search_cache.items() if current_time - v['timestamp'] > 3600]
    for k in expired_searches:
        search_cache.pop(k, None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_ids.add(user_id)
    welcome_text = """
📚 *Welcome to Free eBooks Downloader Bot!*

I help you find and download free eBooks from legal sources and Z-Library.

*Available Commands:*
- /search <book name> - Search for books
- /help - Show help information
- /about - About this bot
- /status - Check bot status

*Example:* `/search Pride and Prejudice`

*Sources:*
📖 Project Gutenberg (70,000+ free books)
📚 Internet Archive (millions of free books)
📱 Z-Library (additional sources, may require login for downloads)

_Note: Some Z-Library downloads may require an account._
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_ids.add(user_id)
    help_text = """
📖 *eBooks Downloader Bot Help*

*Commands:*
- `/start` - Start the bot
- `/search <book title>` - Search for books (use Next/Previous for more results)
- `/help` - Show this help
- `/about` - About this bot
- `/status` - Check bot status
- `/broadcast <message>` - (Admins only) Send message to all users

*How to use:*
1️⃣ Use `/search` followed by the book title
2️⃣ View details with ✅ Preview/Details or navigate with Next/Previous
3️⃣ Click download to get the book

*Supported formats:*
- EPUB (Project Gutenberg)
- PDF (Internet Archive)
- Various (Z-Library, may vary)

*Note:* Gutenberg and Archive provide free, public domain books. Z-Library may require an account for some downloads.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_ids.add(user_id)
    about_text = """
ℹ️ *About Free eBooks Downloader Bot*

This bot provides access to books from:

📖 *Project Gutenberg*
- 70,000+ free eBooks
- Classic literature
- Public domain works

📚 *Internet Archive*
- Millions of free books
- Academic texts
- Historical documents

📱 *Z-Library*
- Additional book sources
- Various formats
- May require login

🔒 *Legal Note*
- Gutenberg and Archive provide public domain books
- Z-Library access may depend on account status

Built with ❤️ for book lovers worldwide.
    """
    await update.message.reply_text(about_text, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_ids.add(user_id)
    try:
        stats = bot_stats.get_stats()
        health = await downloader.check_health()
        
        source_status = (
            f"📖 Project Gutenberg: {'✅ Online' if health['gutenberg'] else '❌ Offline'}\n"
            f"📚 Internet Archive: {'✅ Online' if health['archive'] else '❌ Offline'}\n"
            f"📱 Z-Library: {'✅ Online' if health['zlibrary'] else '❌ Offline'}"
        )
        
        status_text = f"""
🤖 *Bot Status*

⏰ *Uptime*: {stats['uptime']}
🔍 *Total Searches*: {stats['search_count']}
👥 *Users*: {stats['user_count']}
📦 *Cache Size*: {stats['cache_size']} entries
🚦 *Your Remaining Searches*: {rate_limiter.remaining_requests(user_id)} (resets every minute)

*Source Availability*:
{source_status}

💡 Use `/search` to find books or `/help` for more commands.
        """
        await update.message.reply_text(status_text, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Status command error for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ Error retrieving bot status. Please try again later.",
            parse_mode='Markdown'
        )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "❌ You are not authorized to use this command.",
            parse_mode='Markdown'
        )
        return
    
    if not broadcast_limiter.is_allowed(user_id):
        await update.message.reply_text(
            "⚠️ Broadcast rate limit exceeded. Please wait 5 minutes and try again.",
            parse_mode='Markdown'
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "Please provide a message to broadcast.\n\n*Example:* `/broadcast Maintenance scheduled at 2 AM UTC`",
            parse_mode='Markdown'
        )
        return
    
    message = ' '.join(context.args)
    if len(message) > 4096:
        await update.message.reply_text(
            "❌ Message is too long (max 4096 characters). Please shorten it.",
            parse_mode='Markdown'
        )
        return
    
    broadcast_msg = await update.message.reply_text(
        f"📢 Broadcasting message to {len(user_ids)} users...",
        parse_mode='Markdown'
    )
    
    success_count = 0
    fail_count = 0
    
    for uid in user_ids:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 *Broadcast Message*\n\n{message}",
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {uid}: {e}")
            fail_count += 1
    
    await broadcast_msg.edit_text(
        f"📢 *Broadcast Complete*\n\n✅ Sent to {success_count} users\n❌ Failed for {fail_count} users",
        parse_mode='Markdown'
    )

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global cache_counter
    user_id = update.effective_user.id
    user_ids.add(user_id)
    if not rate_limiter.is_allowed(user_id):
        await update.message.reply_text(
            "⚠️ You're searching too quickly. Please wait a minute and try again.",
            parse_mode='Markdown'
        )
        return
    
    query = None
    page = 1
    is_callback = update.callback_query is not None
    
    if is_callback:
        query = update.callback_query
        await query.answer()
        callback_data = query.data.split(':')
        if len(callback_data) != 3 or callback_data[0] not in ['next_page', 'prev_page']:
            await query.edit_message_text(
                "❌ Invalid pagination request.",
                parse_mode='Markdown'
            )
            return
        query_text = callback_data[1]
        page = int(callback_data[2])
        if callback_data[0] == 'next_page':
            page += 1
        elif callback_data[0] == 'prev_page':
            page = max(1, page - 1)
        query = query_text
    else:
        if not context.args:
            await update.message.reply_text(
                "Please provide a book title to search.\n\n*Example:* `/search Pride and Prejudice`",
                parse_mode='Markdown'
            )
            return
        query = ' '.join(context.args)
    
    search_msg = None
    if is_callback:
        search_msg = query
    else:
        search_msg = await update.message.reply_text(f"🔍 Searching for '*{query}*'...", parse_mode='Markdown')
    
    try:
        cleanup_cache()
        
        cache_key = f"query:{query}:page:{page}"
        cached = search_cache.get(cache_key)
        
        results = []
        if cached and cached['timestamp'] + 3600 > time.time():
            results = cached['results']
        else:
            if not is_callback:
                bot_stats.increment_searches()
            
            results = await downloader.search_all_sources(query, limit=36, page=page)
            
            search_cache[cache_key] = {
                'results': results,
                'timestamp': time.time(),
                'total': len(results)
            }
        
        if not results:
            await search_msg.edit_message_text(
                "❌ No books found on this page. Try a different search term or go to previous page.",
                parse_mode='Markdown'
            )
            return
        
        results.sort(key=lambda x: x.get('download_count', 0), reverse=True)
        
        items_per_page = 12
        total_pages = max(1, (len(results) + items_per_page - 1) // items_per_page)
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_results = results[start_idx:end_idx]
        
        if not page_results:
            await search_msg.edit_message_text(
                "❌ No more results on this page. Try going back.",
                parse_mode='Markdown'
            )
            return
        
        keyboard = []
        for book in page_results:
            source_emoji = {
                'gutenberg': '📖',
                'archive': '📚',
                'zlibrary': '📱'
            }.get(book['source'], '📘')
            
            title = book['title'][:30] + "..." if len(book['title']) > 30 else book['title']
            author = book.get('author', 'Unknown')[:20] + "..." if len(book.get('author', 'Unknown')) > 20 else book.get('author', 'Unknown')
            year = book.get('year', 'Unknown')
            language = book.get('language', 'Unknown')
            file_format = book.get('format', 'Unknown')
            file_size = book.get('file_size', 'Unknown')
            
            book_cache_key = f"b_{md5(str(cache_counter).encode()).hexdigest()[:8]}"
            preview_cache_key = f"p_{md5(str(cache_counter).encode()).hexdigest()[:8]}"
            cache_counter += 1
            book_cache[book_cache_key] = {
                'data': {
                    'source': book['source'],
                    'id': book.get('id') or book.get('url'),
                    'info': book
                },
                'timestamp': time.time()
            }
            book_cache[preview_cache_key] = {
                'data': book,
                'timestamp': time.time()
            }
            
            button_text = (
                f"{source_emoji} {title}\n"
                f"👤 {author} ({year})\n"
                f"🌐 {language} | 📄 {file_format} | 💾 {file_size}"
            )
            keyboard.append([InlineKeyboardButton(button_text, callback_data=book_cache_key)])
            keyboard.append([InlineKeyboardButton("✅ Preview/Details", callback_data=preview_cache_key)])
        
        pagination_buttons = []
        if page > 1:
            pagination_buttons.append(
                InlineKeyboardButton("⬅️ Previous Page", callback_data=f"prev_page:{query}:{page}")
            )
        if page < total_pages or len(page_results) == items_per_page:
            pagination_buttons.append(
                InlineKeyboardButton("➡️ Next Page", callback_data=f"next_page:{query}:{page}")
            )
        if pagination_buttons:
            keyboard.append(pagination_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await search_msg.edit_message_text(
            f"📚 Found *{len(results)}* books for '*{query}*' (Page {page}/{total_pages}):\n\nTap a book to download or Preview/Details for more info:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    except Exception as e:
        logger.error(f"Search error for user {user_id}, query '{query}': {e}")
        await search_msg.edit_message_text(
            "❌ An error occurred during search. Please try again later.",
            parse_mode='Markdown'
        )

async def preview_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    user_ids.add(user_id)
    await query.answer()
    
    try:
        callback_data = query.data
        book_entry = book_cache.get(callback_data)
        if not book_entry:
            await query.edit_message_text(
                "❌ Preview data expired. Please search again.",
                parse_mode='Markdown'
            )
            return
        
        book = book_entry['data']
        source_name = {
            'gutenberg': 'Project Gutenberg',
            'archive': 'Internet Archive',
            'zlibrary': 'Z-Library'
        }.get(book['source'], 'Unknown Source')
        
        if book['source'] == 'zlibrary' and book.get('isbn') == 'Unknown':
            download_info = await downloader.zlibrary.get_download_info(book.get('url'))
            if download_info:
                book['isbn'] = download_info.get('isbn', 'Unknown')
                book['description'] = download_info.get('description', book['description'])
        
        message = f"""
📖 *{book['title']}*
📚 *Source:* {source_name}
👤 *Author(s):* {book.get('author', 'Unknown')}
📅 *Year:* {book.get('year', 'Unknown')}
🌐 *Language:* {book.get('language', 'Unknown')}
📄 *Format:* {book.get('format', 'Unknown')}
💾 *File Size:* {book.get('file_size', 'Unknown')}
🔖 *ISBN:* {book.get('isbn', 'Unknown')}
📝 *Description:* {book.get('description', 'No description available')}
        """
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Results", callback_data="back_to_search")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
    
    except Exception as e:
        logger.error(f"Preview error for user {user_id}, callback {query.data}: {e}")
        await query.edit_message_text(
            "❌ An error occurred while fetching preview. Please try again later.",
            parse_mode='Markdown'
        )

async def download_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    user_ids.add(user_id)
    await query.answer()
    
    try:
        if query.data == "back_to_search":
            await query.edit_message_text(
                "📚 Please start a new search using /search <book title>",
                parse_mode='Markdown'
            )
            return
        
        if query.data.startswith('next_page:') or query.data.startswith('prev_page:'):
            await search_books(update, context)
            return
        
        if query.data.startswith('p_'):
            await preview_book(update, context)
            return
        
        callback_data = query.data
        book_entry = book_cache.get(callback_data)
        if not book_entry:
            await query.edit_message_text(
                "❌ Book data expired. Please search again.",
                parse_mode='Markdown'
            )
            return
        
        book_data = book_entry['data']
        source = book_data['source']
        book_id = book_data['id']
        book_info = book_data['info']
        
        await query.edit_message_text("📥 Preparing your download link...")
        
        download_link = await downloader.get_download_link(book_id, source)
        
        if download_link:
            source_name = {
                'gutenberg': 'Project Gutenberg',
                'archive': 'Internet Archive',
                'zlibrary': 'Z-Library'
            }.get(source, 'Unknown Source')
            file_format = book_info.get('format', 'Unknown')
            
            message = f"""
📖 *Book Ready for Download!*
📚 *Source:* {source_name}
📄 *Format:* {file_format}
🔗 [**Download Book**]({download_link})
💡 *Tip:* {source_name} downloads may require an account or specific software.
            """
            keyboard = [[InlineKeyboardButton("🔙 Search Again", callback_data="back_to_search")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            del book_cache[callback_data]
        else:
            await query.edit_message_text(
                "❌ Couldn't generate download link. Try another book or check Z-Library account requirements.",
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"Download error for user {user_id}, callback {query.data}: {e}")
        await query.edit_message_text(
            "❌ An error occurred. Try again later.",
            parse_mode='Markdown'
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_ids.add(user_id)
    text = update.message.text.lower()
    
    if any(keyword in text for keyword in ['search', 'find', 'book', 'download']):
        await update.message.reply_text(
            "To search for books, use: `/search <book title>`\n\n*Example:* `/search The Great Gatsby`",
            parse_mode='Markdown'
        )
    elif any(keyword in text for keyword in ['help', 'how', 'command']):
        await help_command(update, context)
    elif 'status' in text:
        await status_command(update, context)
    else:
        await update.message.reply_text(
            "👋 Hi! I'm your free eBooks downloader bot.\n\nUse `/help` to see all available commands or `/search` to find books!"
        )

async def webhook_handler(request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        if update:
            await application.process_update(update)
            logger.debug(f"Processed update from user {update.effective_user.id if update.effective_user else 'unknown'}")
        else:
            logger.warning("Received invalid update data")
        return web.Response(status=200)
    except ValueError as e:
        logger.error(f"Webhook JSON decode error: {e}")
        return web.Response(status=400)
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return web.Response(status=500)

async def health_check(request):
    return web.Response(text="OK", status=200)

async def setup_webhook(application, retries=3, delay=5):
    for attempt in range(retries):
        try:
            await application.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
            logger.info(f"Webhook successfully set to {WEBHOOK_URL}")
            return True
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}/{retries} to set webhook failed: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
    logger.error("Failed to set webhook after all retries")
    return False

async def keep_alive():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{BASE_URL}/health") as response:
                    if response.status == 200:
                        logger.info("Sent keep-alive ping")
                    else:
                        logger.warning(f"Keep-alive ping failed: {response.status}")
        except aiohttp.ClientError as e:
            logger.error(f"Keep-alive ping error: {e}")
        await asyncio.sleep(300)

async def main():
    global application
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("search", search_books))
    application.add_handler(CallbackQueryHandler(download_book, pattern="^b_|^p_|^back_to_search|^next_page:|^prev_page:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app = web.Application()
    app.add_routes([
        web.post(WEBHOOK_PATH, webhook_handler),
        web.get('/health', health_check)
    ])
    
    # Start keep_alive in the background
    asyncio.create_task(keep_alive())
    
    await application.initialize()
    if not await setup_webhook(application):
        logger.critical("Webhook setup failed; exiting")
        return
    
    await application.start()
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")
    
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        await runner.cleanup()
        await application.stop()
        await application.shutdown()
        logger.info("Shutdown complete")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Main loop error: {e}")
        raise
