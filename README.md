Below is an updated `README.md` for the Telegram eBook Downloader Bot, reflecting the latest project setup with `main.py` as the primary script, webhook-based architecture, and deployment on Render. This version includes clear instructions for local setup, Render deployment, testing, troubleshooting, and usage, tailored for developers and users. It incorporates the project structure and environment variables from the provided `render.yaml` and `requirements.txt`, ensuring consistency with the current date (May 22, 2025) and context.

### README.md

```markdown
# eBook Downloader Bot

A Telegram bot that enables users to search and download free eBooks from Project Gutenberg, Internet Archive, and Z-Library. Built with Python and deployed on Render, the bot uses a webhook-based architecture for efficient operation. Features include book previews, pagination, rate limiting, admin broadcasts, and status monitoring.

## Features

- **Search Books**: Use `/search <title>` to find eBooks across Project Gutenberg, Internet Archive, and Z-Library.
- **Book Previews**: View detailed information (title, author, year, language, format, file size, ISBN, description) via the "✅ Preview/Details" button.
- **Pagination**: Navigate search results with "Next" and "Previous" buttons.
- **Sources**:
  - 📖 **Project Gutenberg**: 70,000+ public domain eBooks (EPUB).
  - 📚 **Internet Archive**: Millions of free books (PDF).
  - 📱 **Z-Library**: Various formats (may require login for some downloads).
- **Commands**:
  - `/start`: Displays a welcome message.
  - `/help`: Shows usage instructions.
  - `/about`: Provides bot and source information.
  - `/status`: Reports bot uptime, search count, user count, cache size, and source availability.
  - `/broadcast <message>`: Admin-only command to send messages to all users.
- **Rate Limiting**: Limits users to 5 searches per minute and admins to 1 broadcast every 5 minutes.
- **Webhook-Based**: Uses Telegram webhooks for efficient, real-time updates.
- **Health Check**: Includes a `/health` endpoint for Render’s health monitoring and keep-alive pings.
- **Deployment**: Optimized for Render’s free tier with automatic deployment via `render.yaml`.

## Prerequisites

- **Python**: Version 3.10.
- **Telegram Bot Token**: Obtain from [BotFather](https://t.me/BotFather) on Telegram.
- **Render Account**: Sign up at [render.com](https://render.com) for deployment.
- **Git Repository**: Host on GitHub, GitLab, or similar.
- **ngrok** (for local testing): Download from [ngrok.com](https://ngrok.com) to expose your local server for webhook testing.

## Project Structure

```
├── main.py           # Main bot script (webhook-based)
├── requirements.txt  # Python dependencies
├── render.yaml       # Render deployment configuration
├── README.md        # Project documentation
```

## Setup Instructions

### Local Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-repo/ebook-downloader-bot.git
   cd ebook-downloader-bot
   ```

2. **Create a Virtual Environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   This installs:
   - `python-telegram-bot==20.7`
   - `aiohttp==3.9.5`
   - `beautifulsoup4==4.12.3`
   - `aiohttp.web==3.9.5`

4. **Set Environment Variables**:
   ```bash
   export BOT_TOKEN="your_bot_token"
   export BASE_URL="http://localhost:8080"
   export ADMIN_IDS="your_telegram_id,another_id"
   export PORT=8080
   ```
   - `BOT_TOKEN`: From BotFather.
   - `ADMIN_IDS`: Comma-separated Telegram user IDs (e.g., `123456789,987654321`).
   - `BASE_URL`: Local server URL (updated for ngrok in the next step).
   - `PORT`: `8080` (matches `render.yaml`).

5. **Expose Local Server with ngrok**:
   ```bash
   ngrok http 8080
   ```
   Copy the ngrok URL (e.g., `https://abc123.ngrok.io`) and update `BASE_URL`:
   ```bash
   export BASE_URL="https://abc123.ngrok.io"
   ```

6. **Set Telegram Webhook**:
   ```bash
   curl -F "url=https://abc123.ngrok.io/webhook/your_bot_token" https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook
   ```
   Verify:
   ```bash
   curl https://api.telegram.org/botYOUR_BOT_TOKEN/getWebhookInfo
   ```
   Expect: `{"ok":true,"result":{"url":"https://abc123.ngrok.io/webhook/your_bot_token",...}}`

7. **Run the Bot**:
   ```bash
   python main.py
   ```
   Look for log: `Webhook set to https://abc123.ngrok.io/webhook/your_bot_token`.

8. **Test Locally**:
   - Open Telegram and interact with your bot:
     - `/start`: Welcome message.
     - `/search Pride and Prejudice`: Lists books with preview and download options.
     - `/status`: Shows bot stats and source status.
     - Click "✅ Preview/Details" to view book details.
     - Use "Next/Previous" for pagination.
   - Test health endpoint:
     ```bash
     curl http://localhost:8080/health
     ```
     Expect: `OK`

### Deployment on Render

1. **Create a Render Account**:
   Sign up at [render.com](https://render.com).

2. **Push to Git Repository**:
   Ensure all files (`main.py`, `requirements.txt`, `render.yaml`, `README.md`) are in your repository:
   ```bash
   git add .
   git commit -m "Initial setup for Render deployment"
   git push origin main
   ```

3. **Create a Web Service**:
   - In Render, select **New > Web Service** and connect your Git repository.
   - Render will detect `render.yaml` and configure the service automatically.

4. **Set Environment Variables**:
   In Render’s dashboard (Environment section):
   - `BOT_TOKEN`: Your Telegram bot token (set manually for security).
   - `ADMIN_IDS`: Comma-separated Telegram user IDs for admins.
   - `BASE_URL`: Your Render app URL (e.g., `https://ebook-downloader-bot.onrender.com`).
   - `PORT`: `8080` (matches `render.yaml`).
   - Note: `PYTHON_VERSION` (3.10) is set in `render.yaml`.

5. **Deploy**:
   - Render will execute:
     - Build: `pip install -r requirements.txt`
     - Start: `python main.py`
   - Check Render logs for:
     ```
     Webhook set to https://ebook-downloader-bot.onrender.com/webhook/{BOT_TOKEN}
     ```
     ```
     Sent keep-alive ping
     ```

6. **Verify Webhook**:
   ```bash
   curl https://api.telegram.org/botYOUR_BOT_TOKEN/getWebhookInfo
   ```
   Expect: `{"ok":true,"result":{"url":"https://ebook-downloader-bot.onrender.com/webhook/YOUR_BOT_TOKEN",...}}`

7. **Test Deployment**:
   - In Telegram, test:
     - `/start`, `/search Pride and Prejudice`, `/status`, `/help`, `/about`.
     - Preview books and download links.
     - Pagination and admin broadcast (if admin).
   - Verify health endpoint:
     ```bash
     curl https://ebook-downloader-bot.onrender.com/health
     ```
     Expect: `OK`
   - Monitor Render logs for errors or successful interactions.

## Usage

1. **Start the Bot**:
   - Send `/start` to receive a welcome message with available commands.

2. **Search for Books**:
   - Use `/search <book title>` (e.g., `/search The Great Gatsby`).
   - Results include title, author, year, language, format, and file size.
   - Click "✅ Preview/Details" for more info or the book title for a download link.

3. **Navigate Results**:
   - Use "Next" and "Previous" buttons for additional results.

4. **Check Status**:
   - Send `/status` to view:
     - Uptime, total searches, user count, cache size.
     - Availability of Project Gutenberg, Internet Archive, and Z-Library.

5. **Admin Broadcast**:
   - Admins (specified in `ADMIN_IDS`) can use `/broadcast <message>` to notify all users.
   - Limited to 1 broadcast every 5 minutes.

6. **Notes**:
   - Project Gutenberg and Internet Archive provide free, public domain books.
   - Z-Library may require an account for some downloads; check download links for details.
   - Rate limits ensure fair usage (5 searches per minute).

## Troubleshooting

- **Webhook Not Set**:
  - **Symptom**: Bot doesn’t respond; logs show “Failed to set webhook”.
  - **Fix**: Verify `BOT_TOKEN` and `BASE_URL` in Render’s environment variables. Ensure `BASE_URL` is correct (Render assigns this on deployment).
  - **Manual Fix**:
    ```bash
    curl -F "url=https://ebook-downloader-bot.onrender.com/webhook/YOUR_BOT_TOKEN" https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook
    ```

- **Health Check Failure**:
  - **Symptom**: Render reports service as unhealthy.
  - **Fix**: Ensure `curl https://ebook-downloader-bot.onrender.com/health` returns “OK”. Check logs for server errors. Verify `aiohttp.web==3.9.5` in `requirements.txt`.

- **Z-Library Search Failures**:
  - **Symptom**: Z-Library results are empty or fail.
  - **Fix**: The `zLibrarySearch` class uses `https://z-lib.is`, which may change. Update `self.base_url` in `main.py` to the current Z-Library domain.
  - **Test Locally**:
    ```python
    import asyncio
    from main import downloader
    async def test_zlib():
        results = await downloader.zlibrary.search_books("Pride and Prejudice")
        print(results)
    asyncio.run(test_zlib())
    ```

- **Render Free Tier Spindown**:
  - **Symptom**: Bot responds slowly after inactivity.
  - **Fix**: The `keep_alive` function pings `/health` every 5 minutes to prevent spindown. If delays persist, upgrade to Render’s `starter` plan for dedicated resources.

- **Build Failure**:
  - **Symptom**: Render build fails (e.g., dependency errors).
  - **Fix**: Check logs for missing packages or Python version mismatches. Ensure `requirements.txt` matches the provided version and `PYTHON_VERSION: 3.10` in `render.yaml`.

- **Bot Not Responding**:
  - **Symptom**: Commands like `/start` or `/search` don’t work.
  - **Fix**: Check Render logs for errors (e.g., invalid `BOT_TOKEN`, port conflicts). Restart the service in Render. Verify webhook setup.

## Contributing

1. Fork the repository.
2. Create a feature branch:
   ```bash
   git checkout -b feature/new-feature
   ```
3. Commit changes:
   ```bash
   git commit -m "Add new feature"
   ```
4. Push to the branch:
   ```bash
   git push origin feature/new-feature
   ```
5. Open a Pull Request on GitHub.

## License

MIT License. See [LICENSE](LICENSE) for details (note: you may need to add a `LICENSE` file to your repository).

## Acknowledgments

- [Project Gutenberg](https://www.gutenberg.org/) for public domain eBooks.
- [Internet Archive](https://archive.org/) for free digital books.
- [Z-Library](https://z-lib.is/) for additional book resources.
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) for the Telegram API library.
- [Render](https://render.com/) for hosting and deployment.
- Built on May 22, 2025, with ❤️ for book lovers worldwide.

## Contact

For issues or feature requests, open an issue on the [GitHub repository](https://github.com/your-repo/ebook-downloader-bot) or contact the maintainer at [your-email@example.com].
```

### Key Features of the README

1. **Comprehensive Documentation**:
   - Covers features, setup (local and Render), usage, troubleshooting, and contribution guidelines.
   - Includes specific commands for testing and deployment, with examples (e.g., `/search Pride and Prejudice`).

2. **Up-to-Date Context**:
   - Reflects the webhook-based `main.py`, `render.yaml`, and `requirements.txt` as of May 22, 2025.
   - Mentions the current Z-Library URL (`https://z-lib.is`) and notes its potential to change.

3. **User-Friendly Instructions**:
   - Step-by-step guides for local testing with `ngrok` and Render deployment.
   - Includes verification steps (e.g., `curl` commands for webhook and health checks).

4. **Troubleshooting**:
   - Addresses common issues like webhook setup, health check failures, Z-Library URL changes, and Render’s free tier spindown.
   - Provides code snippets for debugging (e.g., testing Z-Library searches locally).

5. **Project Structure**:
   - Clearly lists files (`main.py`, `requirements.txt`, `render.yaml`, `README.md`) to avoid confusion about `webhook.py` (which was renamed).

### Integration with Other Files

- **main.py**: The `README` references `main.py` as the primary script, explaining its webhook-based operation and `/health` endpoint.
- **render.yaml**: Instructions align with the provided `render.yaml`, including environment variables (`BOT_TOKEN`, `BASE_URL`, `PORT`, `ADMIN_IDS`) and deployment settings.
- **requirements.txt**: The `README` lists dependencies exactly as in `requirements.txt` for transparency.
- **webhook.py**: Not included in the project structure, as it was renamed to `main.py`. The `README` avoids confusion by focusing on the current setup.

### Deployment Verification

To ensure the `README` instructions work, follow these steps after updating your repository:

1. **Push Changes**:
   ```bash
   git add README.md main.py requirements.txt render.yaml
   git commit -m "Update README and project files for Render deployment"
   git push origin main
   ```

2. **Render Deployment**:
   - Confirm Render detects `render.yaml` and sets up the service.
   - Set environment variables in Render’s dashboard as listed in the `README`.
   - Check logs for “Webhook set to...” and “Sent keep-alive ping”.

3. **Test**:
   - Verify webhook:
     ```bash
     curl https://api.telegram.org/botYOUR_BOT_TOKEN/getWebhookInfo
     ```
   - Test bot commands in Telegram.
   - Check health endpoint:
     ```bash
     curl https://ebook-downloader-bot.onrender.com/health
     ```

### Troubleshooting (from README)

If issues arise, refer to the `Troubleshooting` section in the `README`. Common fixes include:
- **Webhook**: Manually set with `curl` if automatic setup fails.
- **Z-Library**: Update `base_url` in `main.py` if the domain changes.
- **Render**: Check logs for build or runtime errors; ensure `requirements.txt` is correct.

### If You Encounter Issues

Please provide:
- Render logs or local error messages.
- Specific failing step (e.g., webhook setup, `/search` command).
- Environment variable settings (exclude `BOT_TOKEN`).
- Any deviations from the provided `README.md` or other files.

This `README.md` provides a complete guide for setting up, deploying, and using the eBook Downloader Bot, aligned with the updated `main.py`, `render.yaml`, and `requirements.txt`. Let me know if you need further refinements, additional sections (e.g., API documentation), or help with deployment!
