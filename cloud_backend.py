import asyncio
import base64
import json
import os
from pathlib import Path

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="MEDI Cloud API")

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
INDEX_FILE = FRONTEND_DIR / "medi-frontend.html"

load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("ASSEMBLYAI_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "ASSESMBLY_API_KEY isnt here dude..not in the environment"
    )

WS_URL = "wss://agents.assemblyai.com/v1/ws"

VOICE = "anna"

SYSTEM_PROMPT = """
You are MEDI, a voice-first medical communication assistant.

Your grand purpose is to help people communicate their health concerns
clearly and organize information that may be useful to a qualified
healthcare professional.

You are NOT a doctor.

You cannot diagnose a condition.

You cannot prescribe medication.

You cannot tell a user to start, stop, or change prescription
medication.

You MAY:

- Ask relevant questions about symptoms.
- Help users describe their symptoms.
- Organize information provided by the user.
- Explain general health information. 
- Summerize what the user has informed you. 
- Help prepare information for a healthcare professional.
- Encourage emergency care when symptoms may represent an emergency.

VOICE BEHAVIOUR

Speak naturally.

Keep responses concise. 

Usuually respons in one or two sentences.

Ask one or two questions at a time. 

Do not overwhelm the user with long questionnaires.

Do not give long medical lectures. 

Do not repeatedly restate information. 

if the user interrupts you, immediately stop and listen. 

Sound calm, warm, professional and human.

Do not sound robotic. 

CONVERSATION FLOW

When a user reports a healthcare concern:

1. Acknowledge what they said.
2. Ask the most relevant follow-up question.
3. Gradually collect useful information. 
4. Clarify important details. 
5. Summerize the information when appropriate. 
6. Encourage appropriate professional medical care. 

Useful information may include:

- Main concern 
- Symptoms
- Location
- Duration
- Severity
- Whether symptoms are worsening
- Associated symptoms
- Medications
- Allergies
- Relevant medical history

Do NOT ask every question automatically.

Only ask questions relevant to the users situation.

SAFETY

if the user describes symptoms that could indicate a potentially
life-threatening emergency, do not attempt to diagnose them. 

Instead, clearly recommend seeking emergency medical care immediately. 

Potential emergency examples include:

- Severe difficulty breathing
- Severe chest pain
- Loss of consciousness
- Severe uncontrolled bleeding
- Signs of a stroke
- Severe allergic reaction
- Serious injury
- Other potentially life-threatening situations

Do not falsely reassure the user. 

Use languages such as:

"This could be serious, and i dont want to guess about the cause.
Please seek emergency medical care now."

CORE PURPOSE

MEDI does not replace doctors and medical professionals. 

MEDI helps people communicate with doctors and medical professionals. 

The goal is to turn a natural voice conversation into useful, 
organized healthcare communication.
"""

def new_patient():
    return {
        "main_concern": None, 
        "symptoms": [], 
        "duration": None, 
        "severity":None, 
        "location": None, 
        "associated_symptoms": [], 
        "medications": [], 
        "allergies": [], 
        "medical_history":[], 
        "notes":[],

    }

TOOLS = [
    {
        "type": "function", 
        "name": "update_patient_memory", 
        "description":(
            "Update MEDIS structured patient summary using"
            "information explicitly provided by the user."
        ), 
        "parameters":{
            "type": "object", 
            "properties":{
                "main_concern": {
                    "type":"string"
                }, 
                "symptoms":{
                    "type":"array", 
                    "items":{"type":"string"}

                }, 
                "duration":{
                    "type":"string"
                }, 
                "severity":{
                    "type":"string"
                }, 
                "location":{
                    "type":"string"
                }, 
                "associated_symptoms":{
                    "type":"array", 
                    "items":{"type":"string"}
                }, 
                "medications":{
                    "type":"array", 
                    "items":{"type":"string"}
                }, 
                "allergies":{
                    "type":"array", 
                    "items":{"type":"string"}
                }, 
                "medical_history":{
                    "type":"array", 
                    "items":{"type":"string"}
                }, 
                "notes":{
                    "type":"array", 
                    "items":{"type":"string"}
                },
            }
        }
    }
]

async def send_json(websocket, message):
    try:
        await websocket.send_json(message)
    except Exception:
        pass

@app.get("/api/health")
async def health():
    return {
        "status":"online", 
        "service":"MEDI Cloud Backend"
    }

if FRONTEND_DIR.exists():
    app.mount(
        "/static", 
        StaticFiles(directory=FRONTEND_DIR), 
        name="static"
    )

@app.get("/")
async def home():

    if not INDEX_FILE.exists():
        return {
            "error":"MEDI frontend not found.", 
            "expected": str(INDEX_FILE)
        }

    return FileResponse(INDEX_FILE)

async def run_assembly_session(
        browser_ws: WebSocket, 
        patient: dict
):
    headers = {
        "Authorization": f"Bearer {API_KEY}"
    }

    active = True
    session_ready = asyncio.Event()

    try:

        async with websockets.connect(
            WS_URL, 
            additional_headers=headers, 
            open_timeout=30, 
            ping_interval=20, 
            ping_timeout=20, 
            max_size=None
        ) as assembly_ws:

            await assembly_ws.send(
                json.dumps({
                    "type": "session.update", 
                    "session": {
                        "system_prompt": SYSTEM_PROMPT, 

                        "greeting": (
                            "Hi, i am MEDI."
                            "Tell me what you are experiencing, "
                            "and i will help you organize the"
                            "information"
                        ), 

                        "tools": TOOLS, 

                        "input":{
                            "turn_detection":{
                                "interrupt_response": True
                            }
                        }, 

                        "output":{
                            "voice": VOICE
                        }
                    }
                })

            )

            async def browser_to_assembly():

                nonlocal active

                while active:

                    try:
                        message = await browser_ws.receive_json()
                    except Exception:
                        active = False
                        break

                    message_type = message.get("type")

                    if message_type == "start":

                        await send_json(
                            browser_ws, 
                            {
                                "type":"status", 
                                "status":"listening"
                            }
                        )

                    elif message_type == "stop":

                        await send_json(
                            browser_ws, 
                            {
                                "type":"status", 
                                "status":"ready"
                            }
                        )

                    elif message_type == "interrupt":

                        await send_json(
                            browser_ws, 
                            {
                                "type":"status", 
                                "status":"listening"
                            }
                        )

                    elif message_type == "audio":

                        audio = message.get("audio")

                        if audio and session_ready.is_set():

                            await assembly_ws.send(
                                json.dumps({
                                    "type":"input.audio", 
                                    "audio":audio
                                })
                            )

                    elif message_type == "get_state":

                        await send_json(
                            browser_ws, 
                            {
                                "type":"state", 
                                "data":{
                                    "status":"online", 
                                    "patient":patient
                                }
                            }
                        )

                    elif message_type == "text":

                        await send_json(
                            browser_ws, 
                            {
                                "type":"text", 
                                "message":"MEDI cloud server is ON!"
                            }
                        )
            async def assembly_to_browser():

                nonlocal active

                pending_tools = []

                async for raw in assembly_ws:

                    event = json.loads(raw)
                    event_type = event.get("type")

                    if event_type == "session.ready":

                        session_ready.set()

                        await send_json(
                            browser_ws, 
                            {
                                "type":"status",
                                "status":"ready"
                            }
                        )

                    elif event_type == "transcript.user":

                        text = event.get(
                            "text", 
                            ""
                        ).strip()

                        if text:

                            await send_json(
                                browser_ws, 
                                {
                                    "type":"transcript", 
                                    "role":"user", 
                                    "text":text
                                }
                            )

                    elif event_type == "reply.audio":

                        audio_data = event.get("data")

                        if audio_data:

                            await send_json(
                                browser_ws, 
                                {
                                    "type":"audio", 
                                    "audio":audio_data
                                }
                            )

                    elif event_type == "transcript.agent":

                        text = event.get(
                            "text", 
                            ""
                        ).strip()

                        if text:

                            await send_json(
                                browser_ws, 
                                {
                                    "type":"transcript", 
                                    "role":"assistant", 
                                    "text":text
                                }
                            )

                    elif event_type == "tool.call":

                        call_id = event.get("call_id")
                        name = event.get("name")
                        arguments = event.get(
                            "arguments",
                            {}
                        )

                        if isinstance(arguments, str):

                            try:
                                arguments = json.loads(arguments)
                            except Exception:
                                arguments = {}

                        result = None

                        if name == "update_patient_memory":

                            for key, value in arguments.items():

                                if key not in patient:
                                    continue

                                if isinstance(value, list):

                                    for item in value:

                                        if item not in patient[key]:
                                            patient[key].append(item)

                                elif value:

                                    patient[key] = value

                            await send_json(
                                browser_ws,
                                {
                                    "type": "patient_update",
                                    "data": patient
                                }
                            )

                            result = {
                                "success": True,
                                "message": "Patient summary updated."
                            }
                        else:

                            result = {
                                "success": False,
                                "message": (
                                    f"Unknown tool: {name}"
                                )
                            }

                        pending_tools.append({
                            "call_id": call_id,
                            "result": result
                        })

                    elif event_type == "reply.done":

                        for tool in pending_tools:

                            await assembly_ws.send(
                                json.dumps({
                                    "type":"tool.result", 
                                    "call_id":tool["call_id"], 
                                    "result":json.dumps(
                                        tool["result"]
                                    )
                                })
                            )

                        pending_tools.clear()

                    elif event_type == "session.error":

                        print(
                            "[ASSEMBLYAI ERROR]", 
                            event
                        )

                        await send_json(
                            browser_ws, 
                            {
                                "type":"error", 
                                "message":(
                                    "MEDI encounterd a voice "
                                    "connection error."
                                )
                            }
                        )
            await asyncio.gather(
                browser_to_assembly(), 
                assembly_to_browser()
            )

    except Exception as error:

        print(
            "[MEDI CLOUD ERROR]", 
            repr(error)
        )

        try:
            await send_json(
                browser_ws, 
                {
                    "type":"error", 
                    "message":"MEDI cloud connection failed"
                }
            )
        except Exception:
            pass

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket
):

    await websocket.accept()

    print("\n[MEDI CLOUD] Browser connected")

    patient = new_patient()

    await send_json(
        websocket, 
        {
            "type":"state", 
            "data":{
                "status":"starting", 
                "user_message":"", 
                "agent_message":"", 
                "patient":patient
            }
        }
    )

    try:

        await run_assembly_session(
            websocket, 
            patient
        )

    except WebSocketDisconnect:

        print(
            "\n[MEDI CLOUD] Browser disconnected"
        )

    except Exception as error:

        print(
            "\n[MEDI CLOUD ERROR]", 
            repr(error)
        )

    
                  
                





                        

                        
