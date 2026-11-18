import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent
from livekit.plugins import google

from prompts import obtener_instrucciones_con_fecha, GREETING_MESSAGE
from tools import LogronoDeporteTools

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

logger = logging.getLogger("logrono-voice-agent")
logger.setLevel(logging.INFO)


class Assistant(Agent, LogronoDeporteTools):
    def __init__(self) -> None:
        super().__init__(instructions=obtener_instrucciones_con_fecha())
        LogronoDeporteTools.__init__(self)

    async def on_enter(self) -> None:
        logger.info("Agente conectado a la sala. Generando saludo y menú inicial...")
        await asyncio.sleep(0.4)
        await self.session.generate_reply(
            user_input="Hola, acabo de llamar.",
            instructions=f"Saluda al usuario inmediatamente diciendo exactamente este mensaje completo: '{GREETING_MESSAGE}'",
        )


server = AgentServer()


@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    logger.info(f"Nueva solicitud de sala recibida: {ctx.room.name}")

    instrucciones_actuales = obtener_instrucciones_con_fecha()

    session = AgentSession(
        llm=google.realtime.RealtimeModel(
            model="gemini-3.8-live",
            api_version="v1alpha",
            api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
            voice="Puck",
            language="es-ES",
            temperature=0.2,
            instructions=instrucciones_actuales,
        ),
    )

    @ctx.room.on("sip_dtmf_received")
    def on_dtmf_received(dtmf: rtc.SipDTMF):
        digito = getattr(dtmf, "digit", "")
        logger.info(f"[DTMF] Tecla pulsada por el usuario: '{digito}'")
        if digito:
            asyncio.create_task(
                session.generate_reply(
                    user_input=f"He pulsado la tecla {digito} del menú.",
                    instructions=f"El usuario acaba de pulsar la opción {digito} del menú inicial. Atiéndele según esa opción.",
                )
            )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
    )


if __name__ == "__main__":
    agents.cli.run_app(server)