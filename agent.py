import logging
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent
from livekit.plugins import google

from prompts import AGENT_INSTRUCTION, GREETING_MESSAGE
from api_tools import LogronoDeporteAPI

load_dotenv(".env")

logger = logging.getLogger("logrono-voice-agent")
logger.setLevel(logging.INFO)


class Assistant(Agent, LogronoDeporteAPI):
    def __init__(self) -> None:
        super().__init__(instructions=AGENT_INSTRUCTION)

    async def on_enter(self) -> None:
        """
        Este método oficial de LiveKit 1.x se ejecuta automáticamente
        en el instante exacto en que el agente entra en la sesión activa
        y el canal de audio con el usuario ya está listo.
        """
        logger.info("Agente conectado a la sala. Generando saludo inicial...")
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
            voice="Puck",
            temperature=0.8,
            instructions=AGENT_INSTRUCTION,
        )
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
    )


if __name__ == "__main__":
    agents.cli.run_app(server)