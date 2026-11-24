import os
import time
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent
from livekit.plugins import google

from prompts import obtener_instrucciones_con_fecha, GREETING_MESSAGE
from tools import LogronoDeporteTools
from analitica_y_datos.database import guardar_sesion_llamada_db

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

logger = logging.getLogger("logrono-voice-agent")
logger.setLevel(logging.INFO)


class Assistant(Agent, LogronoDeporteTools):
    def __init__(self) -> None:
        super().__init__(instructions=obtener_instrucciones_con_fecha())
        LogronoDeporteTools.__init__(self)

    async def on_enter(self) -> None:
        logger.info("Agente conectado a la sala. Generando saludo y menú inicial...")
        await asyncio.sleep(0.5)
        await self.session.generate_reply(
            user_input="Hola, acabo de llamar.",
            instructions=f"Saluda al usuario inmediatamente diciendo exactamente este mensaje completo: '{GREETING_MESSAGE}'",
        )


server = AgentServer()


@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    logger.info(f"Nueva solicitud de sala recibida: {ctx.room.name}")

    inicio_timestamp = time.time()
    inicio_iso = datetime.now().isoformat(timespec="seconds")
    turnos_dialogo: list[dict] = []
    herramientas_usadas: list[str] = []

    asistente = Assistant()
    instrucciones_actuales = obtener_instrucciones_con_fecha()

    session = AgentSession(
        llm=google.realtime.RealtimeModel(
            model="gemini-3.8-live",
            api_version="v1alpha",
            api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
            voice="Puck",
            language="es-ES",
            temperature=0.4,
            instructions=instrucciones_actuales,
        ),
    )

    @session.on("conversation_item_added")
    def on_conversation_item(event):
        texto = getattr(event.item, "text_content", None)
        if not texto or texto.strip() == "Hola, acabo de llamar.":
            return
        rol = "usuario" if getattr(event.item, "role", "") == "user" else "agente"
        turnos_dialogo.append({
            "rol": rol,
            "texto": texto.strip(),
            "hora": datetime.now().strftime("%H:%M:%S"),
        })

    @session.on("function_tools_executed")
    def on_tools_executed(event):
        for fc in event.function_calls:
            if fc.name not in herramientas_usadas:
                herramientas_usadas.append(fc.name)

    async def guardar_al_finalizar() -> None:
        duracion = time.time() - inicio_timestamp
        dni_actual = str(asistente.sesion_abonado.get("dni", "")) if asistente.sesion_abonado.get("verificado") else ""

        await guardar_sesion_llamada_db(
            sala=ctx.room.name or "consola-local",
            inicio_iso=inicio_iso,
            duracion_seg=duracion,
            turnos_dialogo=turnos_dialogo,
            herramientas_usadas=herramientas_usadas,
            dni_verificado=dni_actual,
        )

    ctx.add_shutdown_callback(guardar_al_finalizar)

    @ctx.room.on("sip_dtmf_received")
    def on_dtmf_received(dtmf: rtc.SipDTMF):
        if dtmf.digit:
            logger.info(f"[DTMF] Tecla pulsada por el usuario: '{dtmf.digit}'")
            asyncio.create_task(
                session.generate_reply(
                    user_input=f"He pulsado la tecla {dtmf.digit} del menú.",
                    instructions=f"El usuario acaba de pulsar la opción {dtmf.digit} del menú inicial. Atiéndele según esa opción.",
                )
            )

    await session.start(
        room=ctx.room,
        agent=asistente,
    )


if __name__ == "__main__":
    agents.cli.run_app(server)