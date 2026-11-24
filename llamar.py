import os
import uuid
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from livekit.api import AccessToken, VideoGrants

load_dotenv()
app = FastAPI()

HTML_LLAMADA = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Asistente de Voz</title>
  <script src="https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"></script>
  <style>
    * { box-sizing: border-box; font-family: system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f5f7; padding: 20px; }
    .card { width: 100%; max-width: 360px; background: #fff; border-radius: 16px; padding: 28px 24px; text-align: center; box-shadow: 0 10px 28px rgba(0,0,0,.08); }
    h1 { margin: 0 0 8px; font-size: 1.3rem; }
    #estado { display: inline-block; padding: 6px 14px; border-radius: 999px; background: #eef2f6; font-size: .85rem; margin: 12px 0 22px; }
    button { width: 100%; padding: 14px; border: 0; border-radius: 12px; font-size: 1rem; font-weight: 600; cursor: pointer; color: #fff; background: #1a73e8; }
    button.colgar { background: #202124; }
    button:disabled { opacity: .6; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Asistente de Voz</h1>
    <div id="estado">Listo para llamar</div>
    <button id="btn">Iniciar llamada</button>
  </div>
  <script>
    let room = null;
    const btn = document.getElementById("btn");
    const estado = document.getElementById("estado");

    async function colgar() {
      if (room) { await room.disconnect(); room = null; }
      document.querySelectorAll("audio[data-lk]").forEach(el => el.remove());
      estado.textContent = "Llamada finalizada";
      btn.textContent = "Iniciar llamada";
      btn.classList.remove("colgar");
      btn.disabled = false;
    }

    btn.addEventListener("click", async () => {
      if (room) { btn.disabled = true; await colgar(); return; }
      btn.disabled = true;
      estado.textContent = "Conectando...";
      try {
        const r = await fetch("/api/token");
        if (!r.ok) throw new Error("Error al generar token");
        const { url, token } = await r.json();
        room = new LivekitClient.Room();
        room.on(LivekitClient.RoomEvent.TrackSubscribed, track => {
          if (track.kind === LivekitClient.Track.Kind.Audio) {
            const el = track.attach();
            el.dataset.lk = "1";
            document.body.appendChild(el);
          }
        });
        room.on(LivekitClient.RoomEvent.Disconnected, () => colgar());
        await room.connect(url, token);
        await room.startAudio();
        await room.localParticipant.setMicrophoneEnabled(true);
        estado.textContent = "En llamada — puedes hablar";
        btn.textContent = "Colgar llamada";
        btn.classList.add("colgar");
        btn.disabled = false;
      } catch (e) {
        estado.textContent = "Error: " + e.message;
        await colgar();
      }
    });
  </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def pagina_llamada():
    return HTMLResponse(HTML_LLAMADA)


@app.get("/api/token")
async def generar_token():
    url = os.getenv("LIVEKIT_URL")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    if not all([url, api_key, api_secret]):
        raise HTTPException(status_code=500, detail="Faltan variables LIVEKIT_* en .env")

    sala = f"demo-{uuid.uuid4().hex[:8]}"
    token = (
        AccessToken(api_key, api_secret)
        .with_identity(f"usuario-{uuid.uuid4().hex[:6]}")
        .with_grants(VideoGrants(room_join=True, room=sala))
        .to_jwt()
    )
    return {"url": url, "token": token, "room": sala}