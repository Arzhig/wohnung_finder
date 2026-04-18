# wohnung_finder
Finding a place in Berlin is tough. This project is transitioning to a Telegram-based notifier that monitors listings from Berlin's six landeseigene Wohnungsbaugesellschaften.

## Current implementation status
- Modular crawler architecture is in place (`scrapers/`, `shared/`, `database.py`, `config.py`, `main.py`).
- WBM parser is implemented and running through the shared pipeline.
- The remaining five providers are scaffolded and ready for parser implementation.
- Telegram notification sending is wired via bot token and database-driven subscriptions.
- Telegram command worker is active with `/start`, `/status`, `/subscribe`, `/unsubscribe`, and `/filters`.

## Crawl access constraints
- Maximum 2 outbound crawl calls per minute (global).
- Randomized normal-distribution delay between crawl calls.
- No crawl calls between 00:00 and 06:00 Europe/Berlin local time.

See `PLAN.md` for migration milestones and next steps.

## Telegram Commands
- `/start` subscribe current chat to all enabled companies.
- `/status` show current subscriptions and active filters.
- `/subscribe <company|all>` subscribe for one company or all.
- `/unsubscribe <company|all>` remove one or all subscriptions.
- `/filters max_rent=<n> min_size=<n> min_rooms=<n>` set numeric filters.
- `/filters clear` remove all filters.

## Environment notes
- `TELEGRAM_CHAT_IDS` is a comma-separated list of numeric chat IDs (example: `123456789,-1001234567890`).
- You can start with your own user chat ID and let `/start` register your chat in the DB.

## Startup self-check
- Run `python main.py --check` to validate bot token, database initialization, and enabled scraper wiring without starting the monitor loop.
