"""Bothost entry point. The platform runs this file from the project root."""
import asyncio
from app.main import main

if __name__ == "__main__":
    asyncio.run(main())
