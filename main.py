"""Convenience entry point that delegates to bot.main."""

from bot.main import main

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
