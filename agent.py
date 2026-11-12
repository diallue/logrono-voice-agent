import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent
from livekit.plugins import google

from prompts import AGENT_INSTRUCTION, GREETING_MESSAGE
from api_tools import LogronoDeporteAPI

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

logger = logging.getLogger("logrono-voice-agent")
logger.setLevel(logging.INFO)

class Assistant(Agent, LogronoDeporteAPI):
    def __init__(self) -> None:
        Agent.__init__(self, instructions=AGENT_INSTRUCTION)
        LogronoDeporteAPI.__init__(self)

    async def on_enter(self) -> None:
        logger.info("Agente conectado a la sala. Generando saludo inicial...")
        await asyncio.sleep(0.4)
        await self.session.generate_reply(
            user_input="Hola, acabo de conectarme.",
            instructions=f"Saluda al usuario inmediatamente diciendo exactamente esto: '{GREETING_MESSAGE}'"
        )

server = AgentServer()

@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    logger.info(f"Nueva solicitud de sala recibida: {ctx.room.name}")

    session = AgentSession(
        llm=google.realtime.RealtimeModel(
            model="gemini-3.8-live",
            api_version="v1alpha",
            api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
            voice="Puck",
            language="es-ES",
            temperature=0.6,
            instructions=AGENT_INSTRUCTION,
        ),
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
    )

if __name__ == "__main__":
    agents.cli.run_app(server)