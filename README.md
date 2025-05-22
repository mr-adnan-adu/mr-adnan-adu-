# Telegram eBooks Downloader Bot

A powerful Telegram bot that helps users find and download free eBooks from multiple legal sources including Project Gutenberg, Internet Archive, and Z-Library.

## 🌟 Features

- **Multi-Source Search**: Searches across Project Gutenberg, Internet Archive, and Z-Library
- **Smart Caching**: MongoDB-powered caching system with in-memory fallback
- **Rate Limiting**: Built-in protection against spam and abuse
- **User Management**: Tracks users and usage statistics
- **Admin Controls**: Broadcast messages to all users
- **Health Monitoring**: Built-in health checks and status monitoring
- **Multiple Formats**: Supports EPUB, PDF, and HTML formats
- **Pagination**: Navigate through search results easily
- **Book Previews**: Detailed book information before downloading

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- MongoDB Atlas account (optional, fallback to in-memory storage)
- Telegram Bot Token from [@BotFather](https://t.me/botfather)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/mr-adnan-adu/telegram-ebooks-bot.git
   cd telegram-ebooks-bot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   
   Create a `.env` file or set the following environment variables:
   ```bash
   BOT_TOKEN=your_telegram_bot_token
   BASE_URL=https://your-app-url.com
   PORT=8080
   ADMIN_IDS=your_telegram_user_id,another_admin_id
   MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/
   MONGODB_DB_NAME=ebook_bot
   ```

4. **Run the bot**
   ```bash
   python main.py
   ```

## 📋 Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `BOT_TOKEN` | Telegram Bot Token from BotFather | ✅ Yes | - |
| `BASE_URL` | Your app's public URL (for webhooks) | ✅ Yes | - |
| `PORT` | Port for the web server | ❌ No | `8080` |
| `ADMIN_IDS` | Comma-separated list of admin user IDs | ❌ No | - |
| `MONGODB_URI` | MongoDB connection string | ❌ No | - |
| `MONGODB_DB_NAME` | MongoDB database name | ❌ No | `ebook_bot` |

## 🤖 Bot Commands

### User Commands
- `/start` - Welcome message and bot introduction
- `/search <book title>` - Search for books across all sources
- `/help` - Show help information and usage guide
- `/about` - Learn about the bot and its sources
- `/status` - Check bot status and your rate limits

### Admin Commands
- `/broadcast <message>` - Send a message to all bot users

### Usage Examples
```
/search Pride and Prejudice
/search George Orwell
/search Python programming
/search Shakespeare
```

## 📚 Supported Sources

### 📖 Project Gutenberg
- **Collection**: 70,000+ free public domain eBooks
- **Formats**: EPUB, HTML
- **Content**: Classic literature, historical texts
- **Registration**: Not required

### 📚 Internet Archive
- **Collection**: Millions of books and documents
- **Formats**: PDF
- **Content**: Academic texts, historical documents
- **Registration**: Not required

### 📱 Z-Library
- **Collection**: Large collection of books
- **Formats**: Various (PDF, EPUB, etc.)
- **Content**: Academic and general books
- **Registration**: May be required for downloads

## 🏗️ Architecture

### Core Components

1. **MongoDBManager**: Handles database operations with fallback to in-memory storage
2. **eBookDownloader**: Manages searches across multiple sources
3. **zLibrarySearch**: Specialized Z-Library search implementation
4. **RateLimiter**: Prevents abuse with configurable rate limits
5. **BotStats**: Tracks usage statistics and uptime

### Search Flow

```
User Query → Rate Limit Check → Cache Check → Multi-Source Search → Results Display → Download Link Generation
```

### Database Schema

#### Collections
- `users` - User information and activity tracking
- `searches` - Search history and caching
- `rate_limits` - Rate limiting data
- `cache` - Search result caching
- `stats` - Bot usage statistics

## 🔧 Deployment

### Render.com (Recommended)

1. Fork this repository
2. Connect your GitHub to Render
3. Create a new Web Service
4. Set environment variables in Render dashboard
5. Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/mr-adnan-adu/telegram-ebooks-bot)

### Heroku

1. Install Heroku CLI
2. Create new app: `heroku create your-app-name`
3. Set environment variables: `heroku config:set BOT_TOKEN=your_token`
4. Deploy: `git push heroku main`

### Railway

1. Connect GitHub repository to Railway
2. Set environment variables
3. Deploy automatically

### VPS/Docker

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8080

CMD ["python", "main.py"]
```

## 📊 Monitoring

### Health Check Endpoint
- **URL**: `https://your-app.com/health`
- **Method**: GET
- **Response**: JSON with bot statistics

### Metrics Tracked
- Total searches performed
- Number of active users
- Cache performance
- Source availability
- Bot uptime

## 🛡️ Security & Rate Limiting

### Rate Limits
- **Search**: 5 requests per minute per user
- **Broadcast**: 1 request per 5 minutes (admins only)
- **Source APIs**: Individual rate limiting per source

### Security Features
- Input validation and sanitization
- MongoDB injection prevention
- Error handling without data exposure
- Admin-only commands protection

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes
4. Add tests if applicable
5. Commit: `git commit -am 'Add new feature'`
6. Push: `git push origin feature-name`
7. Create a Pull Request

### Development Setup

```bash
# Clone your fork
git clone https://github.com/your-username/telegram-ebooks-bot.git
cd telegram-ebooks-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up development environment variables
cp .env.example .env
# Edit .env with your values

# Run in development mode
python main.py
```

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚖️ Legal Notice

This bot only provides access to:
- Public domain books from Project Gutenberg
- Freely available documents from Internet Archive
- Legal content from Z-Library

All content is sourced from legal, public repositories. The bot respects copyright laws and DMCA guidelines.

## 🐛 Troubleshooting

### Common Issues

**Bot not responding to commands**
- Check if webhook is set correctly
- Verify BOT_TOKEN is valid
- Check server logs for errors

**Search returning no results**
- Try different search terms
- Check if sources are online using `/status`
- Verify internet connectivity

**MongoDB connection issues**
- Check MONGODB_URI format
- Ensure IP is whitelisted in MongoDB Atlas
- Bot will fallback to in-memory storage

**Rate limit errors**
- Wait for rate limit to reset (1 minute)
- Check if multiple users share same IP

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/mr-adnan-adu/telegram-ebooks-bot/issues)
- **Discussions**: [GitHub Discussions](https://github.com/mr-adnan-adu/telegram-ebooks-bot/discussions)
- **Email**: [Your Email]

## 🙏 Acknowledgments

- [Project Gutenberg](https://www.gutenberg.org/) for free public domain books
- [Internet Archive](https://archive.org/) for historical documents
- [Z-Library](https://z-lib.is/) for additional book sources
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) library
- All contributors and users of this bot

---

**Made with ❤️ for book lovers worldwide**

*If you find this bot useful, please ⭐ star the repository!*
