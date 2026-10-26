import asyncio
import logging
from aiogram import Bot, Dispatcher
from app.config import settings
from app.db.base import Base
from app.db.session import engine
from app.handlers import common_router, finance_router, simulator_router
from app.services.scheduler import run_period_scheduler

async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

async def main() -> None:
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await init_db()
    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_routers(common_router, finance_router, simulator_router)
    stop_event = asyncio.Event()
    scheduler_task = asyncio.create_task(run_period_scheduler(stop_event))
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        stop_event.set()
        await scheduler_task
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
