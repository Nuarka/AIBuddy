# serve.py — кроссплатформенно для локалки (Windows) и Render (Linux)
import os
import sys
import asyncio
import signal
import contextlib
from aiohttp import web

PORT = int(os.environ.get("PORT", "10000"))

async def health(_):
    return web.Response(text="ok")

async def start_http():
    app = web.Application()
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    while True:
        await asyncio.sleep(3600)

async def run_bot_forever():
    while True:
        proc = await asyncio.create_subprocess_exec(sys.executable, "Main.py")
        rc = await proc.wait()
        await asyncio.sleep(1)  # чтобы не крутить рестарт слишком быстро

async def main():
    stop = asyncio.Event()

    # Сигналы: на Linux/Render повесим обработчики, на Windows — мягко пропустим
    try:
        loop = asyncio.get_running_loop()
        for sname in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sname, None)
            if sig is not None:
                try:
                    loop.add_signal_handler(sig, stop.set)
                except NotImplementedError:
                    pass
    except Exception:
        pass

    t_http = asyncio.create_task(start_http(), name="http")
    t_bot  = asyncio.create_task(run_bot_forever(), name="bot")

    try:
        await stop.wait()
    finally:
        t_http.cancel(); t_bot.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(t_http, t_bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
