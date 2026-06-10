import asyncio
from deepgram import DeepgramClient, LiveOptions
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    dg_client = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
    conn = dg_client.listen.asyncwebsocket.v("1")
    opts = LiveOptions(model="nova-2", language="en-US", encoding="linear16", sample_rate=16000)
    print("starting...")
    res = await conn.start(opts)
    print("started:", res)
    await conn.finish()

asyncio.run(main())
