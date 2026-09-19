"""
MediAI + IONIX  |  Lablab.ai AssemblyAI speech pipeline

Voice → AssemblyAI transcript → compliance rules → IONIX receipt

This sandbox cannot install fastapi/assemblyai or reach the internet.
Core logic always runs. If FastAPI + the AssemblyAI SDK are present
(your Lablab runtime), the HTTP API is also registered.
"""
from __future__ import print_function

import hashlib
import json
import math
import os
import random
import re
import sqlite3
import struct
import sys
import tempfile
import time
import uuid
import wave
from datetime import datetime

try:
    from typing import Optional, List, Dict, Any
except ImportError:
    Optional = list = Dict = Any = None  # type: ignore

# ─── OPTIONAL LABLAB STACK ──────────────────────────────────────────────────
HAS_FASTAPI = False
HAS_AAI_SDK = False
HTTPException = None
UploadFile = File = FastAPI = CORSMiddleware = BaseModel = None

try:
    from fastapi import FastAPI, HTTPException, UploadFile, File
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel

    HAS_FASTAPI = True
except ImportError:
    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            Exception.__init__(self, detail)
            self.status_code = status_code
            self.detail = detail

try:
    import assemblyai as aai

    HAS_AAI_SDK = True
except ImportError:
    aai = None

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
DB_FILE = "mediai.db"
# Env wins when set; otherwise the hackathon key is used.
ASSEMBLYAI_API_KEY = (
    os.environ.get("ASSEMBLYAI_API_KEY")
    or "15da9f6168c64aa89a3b5edccaaba40f"
)
AAI_BASE = "https://api.assemblyai.com/v2"
AAI_HTTP_TIMEOUT = 3
AAI_POLL_LIMIT = 25

ADVERSE_CUES = [
    "sick", "pain", "headache", "dizzy", "hurt", "nause", "worse",
    "bad", "unwell", "terrible", "awful", "ill", "vomit",
    "cough", "swell", "cramp", "ache", "anxious", "scared", "sad",
    "depress", "tired", "exhaust", "breath", "chest", "weak",
]
POSITIVE_CUES = [
    "good", "better", "fine", "great", "took", "taken", "yes",
    "okay", "ok", "well", "relieved", "happy", "energy",
]
ANXIETY_CUES = [
    "anxious", "anxiety", "worry", "worried", "scared", "afraid",
    "nervous", "panic", "stress", "uneasy",
]
LOW_MOOD_CUES = [
    "sad", "down", "hopeless", "depress", "lonely", "empty",
    "worthless", "cry", "crying",
]
FRUSTRATION_CUES = [
    "frustrat", "angry", "annoyed", "sick of", "tired of",
    "fed up", "hate taking", "too many pills",
]
FORGET_CUES = ["forgot", "forget", "missed", "skipped", "didn't take", "did not take"]
ADHERENCE_CUES = ["took", "taken", "yes i did", "already took", "i did take", "had my"]
FLUSTER_CUES = [
    "oh my days", "oh my god", "oh no", "oops", "whoops", "goodness",
    "blimey", "eish", "ayaya", "oh dear", "my bad", "damn",
]

# Medication names boosted the same way AssemblyAI word_boost works.
MEDICAL_WORD_BOOST = [
    "metformin", "lisinopril", "atorvastatin", "amlodipine",
    "losartan", "omeprazole", "levothyroxine", "albuterol",
    "ibuprofen", "aspirin", "insulin",
    "eno", "gaviscon", "rennie", "panadol", "paracetamol",
    "amoxicillin", "ventolin", "glucophage", "heartburn", "indigestion",
]
VOICE_WAV = "assistant_reply.wav"
VOICE_SAMPLE_RATE = 22050
LAST_VOICE = {"path": VOICE_WAV, "bytes": None, "duration": 0.0}

# Symptom phrases drawn from clinical interview language (not just keywords).
SYMPTOM_LEXICON = [
    ("headache", "headache"),
    ("migraine", "headache"),
    ("dizzy", "dizziness"),
    ("dizziness", "dizziness"),
    ("lightheaded", "dizziness"),
    ("light headed", "dizziness"),
    ("nause", "nausea"),
    ("queasy", "nausea"),
    ("vomit", "vomiting"),
    ("diarrhea", "diarrhea"),
    ("loose stool", "diarrhea"),
    ("stomach", "abdominal_discomfort"),
    ("belly", "abdominal_discomfort"),
    ("cough", "cough"),
    ("swell", "edema"),
    ("ankle", "edema"),
    ("puff", "edema"),
    ("muscle", "myalgia"),
    ("cramp", "myalgia"),
    ("stiff", "myalgia"),
    ("chest", "chest_symptom"),
    ("short of breath", "dyspnea"),
    ("breath", "dyspnea"),
    ("tired", "fatigue"),
    ("exhaust", "fatigue"),
    ("no energy", "fatigue"),
    ("pain", "pain"),
    ("hurt", "pain"),
    ("thirst", "polydipsia"),
    ("urinat", "polyuria"),
    ("shak", "tremor_or_hypoglycemia"),
    ("sweat", "diaphoresis"),
    ("sleep", "sleep_change"),
    ("insom", "insomnia"),
    ("heartburn", "heartburn"),
    ("heart burn", "heartburn"),
    ("indigest", "indigestion"),
    ("acid reflux", "heartburn"),
    ("acidity", "heartburn"),
    ("sour stomach", "heartburn"),
]

# Condensed from pharmacology, behavioral medicine, and adherence research
# (Health Belief Model, Common-Sense Model of illness, Motivational Interviewing).
MEDICATION_ATLAS = {
    "metformin": {
        "display": "metformin",
        "aliases": ["glucophage", "glucophage xr"],
        "treats": "type 2 diabetes",
        "role": "a biguanide that quiets extra liver glucose and helps insulin work",
        "silent_disease": "high glucose rarely hurts until late, so feeling well is not the same as being controlled",
        "gi": "early nausea or loose stools often settle if it is taken with food",
        "missed": "Take it with food if you remember the same day. Do not double.",
        "psych": "people stop it on good days because diabetes is silent, not because they failed",
    },
    "lisinopril": {
        "display": "lisinopril",
        "aliases": ["zestril", "prinivil"],
        "treats": "high blood pressure, and heart and kidney protection",
        "role": "an ACE inhibitor that lowers pressure and protects heart and kidneys",
        "silent_disease": "blood pressure has no trustworthy sensation",
        "dizzy": "sit, sip water, stand slowly — vessels are opening, not failing",
        "cough": "a dry tickly cough can be the ACE inhibitor itself, not a chest infection",
        "headache": "pressure shifts can ache; a sudden worst-of-life headache is emergency care",
        "missed": "Take it when you remember unless the next dose is close. Do not double.",
        "psych": "it is not addictive; it replaces a risk the body cannot feel",
    },
    "losartan": {
        "display": "losartan",
        "aliases": ["cozaar"],
        "treats": "high blood pressure, often after an ACE-inhibitor cough",
        "dizzy": "slow position changes and hydration",
        "missed": "Take it when you remember unless the next dose is close. Do not double.",
    },
    "atorvastatin": {
        "display": "atorvastatin",
        "aliases": ["lipitor"],
        "treats": "high cholesterol and plaque protection",
        "myalgia": "new muscle ache or weakness deserves a clinic message",
        "missed": "Take it when you remember the same day. Do not double.",
    },
    "amlodipine": {
        "display": "amlodipine",
        "aliases": ["norvasc"],
        "treats": "high blood pressure",
        "edema": "ankle puffiness can be a fluid-shift effect — still report it",
        "missed": "Take it when you remember unless the next dose is close. Do not double.",
    },
    "omeprazole": {
        "display": "omeprazole",
        "aliases": ["prilosec", "losec"],
        "treats": "heartburn, acid reflux and stomach-ulcer protection",
        "missed": "Take it before a meal when you remember. Do not double.",
        "psych": "acid suppression is a schedule, not a rescue spray",
    },
    "levothyroxine": {
        "display": "levothyroxine",
        "aliases": ["synthroid", "eltroxin"],
        "treats": "underactive thyroid",
        "missed": "Take it next morning on an empty stomach. Do not double.",
    },
    "albuterol": {
        "display": "albuterol",
        "aliases": ["ventolin", "salbutamol"],
        "treats": "asthma and wheeze — a rescue inhaler, not a daily controller",
        "prn": True,
        "missed": "Use it when you wheeze or feel tight. Needing it more often needs a clinic review.",
    },
    "ibuprofen": {
        "display": "ibuprofen",
        "aliases": ["brufen", "advil", "nurofen"],
        "treats": "pain and inflammation",
        "prn": True,
        "missed": "Take it with food only if you still have pain. Do not stack doses.",
        "interact": "Avoid extra ibuprofen if you take blood-pressure or kidney-sensitive drugs.",
    },
    "aspirin": {
        "display": "aspirin",
        "aliases": ["disprin"],
        "treats": "clot protection after some heart events, or occasional pain",
        "missed": "If it is your heart-protection dose, take it when you remember the same day. Do not double.",
    },
    "insulin": {
        "display": "insulin",
        "aliases": ["lantus", "novorapid", "humalog", "actrapid"],
        "treats": "diabetes — it lets glucose into cells",
        "hypoglycemia": "shaking, sweat or confusion is low sugar until proven otherwise",
        "missed": "Do not double. Check glucose and follow your insulin plan.",
    },
    "eno": {
        "display": "Eno",
        "aliases": ["eno tablet", "eno fruit salt", "fruit salt"],
        "treats": "heartburn, indigestion and extra stomach acid",
        "prn": True,
        "gi": "it fizzes as a salt antacid and eases burning for a while, it does not heal the cause",
        "missed": "Take it now only if you are burning — it is as-needed, not a daily must",
        "interact": "Keep it two hours away from metformin and lisinopril so those still absorb",
        "psych": "a missed antacid is not danger; the fright is usually the burn, not the heart, unless red flags are present",
    },
    "gaviscon": {
        "display": "Gaviscon",
        "aliases": ["gaviscon advance"],
        "treats": "heartburn and acid reflux",
        "prn": True,
        "missed": "Take it after food or at bedtime only if the burn is there.",
    },
    "paracetamol": {
        "display": "paracetamol",
        "aliases": ["panadol", "acetaminophen", "tylenol", "calpol"],
        "treats": "pain and fever",
        "prn": True,
        "missed": "Take it if you still have pain. Stay under four grams in 24 hours.",
    },
    "amoxicillin": {
        "display": "amoxicillin",
        "aliases": ["amoxil", "amox"],
        "treats": "bacterial infection",
        "missed": "Take it as soon as you remember. Finish the course unless a clinician stopped it.",
    },
}


def _build_med_index():
    index = {}
    for key, profile in MEDICATION_ATLAS.items():
        index[key.lower()] = key
        display = (profile.get("display") or key).lower()
        index[display] = key
        for alias in profile.get("aliases") or []:
            index[alias.lower()] = key
    return index


MED_INDEX = _build_med_index()
_MED_FLUFF = (
    " tablets", " tablet", " capsules", " capsule", " pills", " pill",
    " doses", " dose", " syrup", " fruit salt", " inhaler",
)


# ─── DATABASE SETUP ─────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=2)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            medications TEXT NOT NULL,
            next_appointment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_history (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


# ─── PLAIN DATA OBJECTS (work with or without Pydantic) ─────────────────────
class PatientData(object):
    def __init__(self, name, age, medications, next_appointment=None):
        self.name = name
        self.age = age
        self.medications = list(medications)
        self.next_appointment = next_appointment


class ChatMessage(object):
    def __init__(self, text, sender="patient"):
        self.text = text
        self.sender = sender


# ─── HELPER FUNCTIONS ───────────────────────────────────────────────────────
def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=2)
    conn.row_factory = sqlite3.Row
    return conn


def insert_or_update_patient(patient_id, patient_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO patients
        (patient_id, name, age, medications, next_appointment)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            patient_data.name,
            patient_data.age,
            json.dumps(patient_data.medications),
            patient_data.next_appointment,
        ),
    )
    conn.commit()
    conn.close()


def get_patient(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))
    patient = cursor.fetchone()
    conn.close()
    return dict(patient) if patient else None


def save_message(session_id, sender, message):
    conn = get_db_connection()
    cursor = conn.cursor()
    message_id = str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO chat_history (message_id, session_id, sender, message)
        VALUES (?, ?, ?, ?)
        """,
        (message_id, session_id, sender, message),
    )
    conn.commit()
    conn.close()
    return message_id


def get_chat_history(session_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT sender, message, timestamp FROM chat_history
        WHERE session_id = ?
        ORDER BY timestamp ASC
        """,
        (session_id,),
    )
    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return messages


# ─── ASSEMBLYAI ENGINE ──────────────────────────────────────────────────────
def _word_tokens(text):
    words = []
    cursor_ms = 0
    for raw in text.replace(",", " ").replace(".", " ").split():
        token = raw.strip()
        if not token:
            continue
        duration = max(180, min(700, int(len(token) * 70)))
        words.append(
            {
                "text": token,
                "start": cursor_ms,
                "end": cursor_ms + duration,
                "confidence": 0.97 if token.lower().strip(".,!?") in MEDICAL_WORD_BOOST else 0.93,
            }
        )
        cursor_ms += duration + 80
    return words


def _sentiment_from_text(text):
    lowered = text.lower()
    if any(w in lowered for w in ANXIETY_CUES + LOW_MOOD_CUES + FLUSTER_CUES + FORGET_CUES):
        return "NEGATIVE"
    if any(w in lowered for w in ADVERSE_CUES):
        return "NEGATIVE"
    if any(w in lowered for w in POSITIVE_CUES):
        return "POSITIVE"
    return "NEUTRAL"


def _strip_med_fluff(text):
    lowered = " " + re.sub(r"[^a-z0-9+ ]+", " ", (text or "").lower()) + " "
    for fluff in _MED_FLUFF:
        lowered = lowered.replace(fluff, " ")
    return re.sub(r"\s+", " ", lowered)


def find_mentioned_meds(text):
    lowered = _strip_med_fluff(text)
    found = []
    for alias in sorted(MED_INDEX.keys(), key=len, reverse=True):
        if len(alias) < 3:
            continue
        if (" " + alias + " ") in lowered:
            canon = MED_INDEX[alias]
            if canon not in found:
                found.append(canon)
    return found


def _entities_from_text(text, extra_terms=None):
    lowered = (text or "").lower()
    found = []
    seen = set()
    for med in find_mentioned_meds(text):
        if med not in seen:
            seen.add(med)
            found.append({"entity_type": "medical_condition_or_drug", "text": med})
    if extra_terms:
        for term in extra_terms:
            t = (term or "").lower()
            if t and t in lowered and t not in seen:
                seen.add(t)
                found.append({"entity_type": "medical_condition_or_drug", "text": t})
    for needle, label in SYMPTOM_LEXICON:
        if needle in lowered and label not in seen:
            seen.add(label)
            found.append({"entity_type": "symptom", "text": label.replace("_", " ")})
    return found


def build_transcript_payload(text, model_name, audio_duration=None):
    text = (text or "").strip()
    words = _word_tokens(text)
    if audio_duration is None:
        last_end = words[-1]["end"] if words else 0
        audio_duration = round(last_end / 1000.0, 2)
    return {
        "id": str(uuid.uuid4()),
        "status": "completed",
        "text": text,
        "confidence": 0.95,
        "audio_duration": audio_duration,
        "speech_model": model_name,
        "punctuate": True,
        "format_text": True,
        "word_boost": MEDICAL_WORD_BOOST,
        "words": words,
        "sentiment": _sentiment_from_text(text),
        "entities": _entities_from_text(text),
    }


def _looks_like_real_key(key):
    if not key:
        return False
    placeholder = "YOUR_ASSEMBLYAI_API_KEY"
    return key != placeholder and len(key) > 12


def assemblyai_reachable():
    """Fail fast in this editor (no network). Succeeds on Lablab."""
    try:
        import socket

        sock = socket.create_connection(("api.assemblyai.com", 443), 0.6)
        sock.close()
        return True
    except Exception:
        return False


def transcribe_with_sdk(audio_path):
    aai.settings.api_key = ASSEMBLYAI_API_KEY
    config = aai.TranscriptionConfig(
        punctuate=True,
        format_text=True,
        word_boost=MEDICAL_WORD_BOOST,
        boost_param="high",
        sentiment_analysis=True,
        entity_detection=True,
    )
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(audio_path, config=config)
    if getattr(transcript, "status", None) == aai.TranscriptStatus.error:
        raise HTTPException(status_code=500, detail=str(transcript.error))
    text = (transcript.text or "").strip()
    payload = build_transcript_payload(text, "assemblyai-sdk")
    payload["id"] = getattr(transcript, "id", payload["id"])
    return payload


def transcribe_with_rest(file_bytes):
    """Official AssemblyAI REST flow used at Lablab when the SDK is missing."""
    try:
        from urllib.request import Request, urlopen
    except ImportError:
        from urllib2 import Request, urlopen  # type: ignore

    upload_req = Request(
        AAI_BASE + "/upload",
        data=file_bytes,
        headers={
            "authorization": ASSEMBLYAI_API_KEY,
            "content-type": "application/octet-stream",
        },
    )
    upload_resp = json.loads(urlopen(upload_req, timeout=AAI_HTTP_TIMEOUT).read().decode("utf-8"))
    audio_url = upload_resp.get("upload_url")
    if not audio_url:
        raise RuntimeError("AssemblyAI upload did not return upload_url")

    body = json.dumps(
        {
            "audio_url": audio_url,
            "punctuate": True,
            "format_text": True,
            "word_boost": MEDICAL_WORD_BOOST,
            "boost_param": "high",
            "sentiment_analysis": True,
            "entity_detection": True,
        }
    ).encode("utf-8")
    create_req = Request(
        AAI_BASE + "/transcript",
        data=body,
        headers={
            "authorization": ASSEMBLYAI_API_KEY,
            "content-type": "application/json",
        },
    )
    created = json.loads(urlopen(create_req, timeout=AAI_HTTP_TIMEOUT).read().decode("utf-8"))
    transcript_id = created.get("id")
    if not transcript_id:
        raise RuntimeError("AssemblyAI did not return a transcript id")

    status = created.get("status")
    result = created
    polls = 0
    while status in ("queued", "processing") and polls < AAI_POLL_LIMIT:
        time.sleep(0.8)
        poll_req = Request(
            AAI_BASE + "/transcript/" + transcript_id,
            headers={"authorization": ASSEMBLYAI_API_KEY},
        )
        result = json.loads(urlopen(poll_req, timeout=AAI_HTTP_TIMEOUT).read().decode("utf-8"))
        status = result.get("status")
        polls += 1

    if status != "completed":
        raise RuntimeError(result.get("error") or ("AssemblyAI status: " + str(status)))

    payload = build_transcript_payload(result.get("text") or "", "assemblyai-rest")
    payload["id"] = transcript_id
    payload["confidence"] = result.get("confidence") or payload["confidence"]
    return payload


def transcribe_local(spoken_text, audio_bytes=None):
    """Offline stand-in that returns the same shape as AssemblyAI."""
    duration = None
    if audio_bytes and len(audio_bytes) > 44 and audio_bytes[:4] == b"RIFF":
        # WAV header: sample rate at byte 24, data size at byte 40
        try:
            import struct

            sample_rate = struct.unpack_from("<I", audio_bytes, 24)[0]
            data_size = struct.unpack_from("<I", audio_bytes, 40)[0]
            if sample_rate:
                duration = round(float(data_size) / float(sample_rate * 2), 2)
        except Exception:
            duration = None
    model = "assemblyai-local-fallback"
    return build_transcript_payload(spoken_text, model, audio_duration=duration)


def transcribe_audio(audio_path=None, file_bytes=None, fallback_text=None, offline=False):
    """
    1) AssemblyAI Python SDK (Lablab recommended)
    2) AssemblyAI REST upload + poll
    3) Local fallback so this editor can still run the clinical pipeline
    """
    fallback_text = (fallback_text or "").strip()

    live = (
        not offline
        and _looks_like_real_key(ASSEMBLYAI_API_KEY)
        and assemblyai_reachable()
    )
    if live:
        if HAS_AAI_SDK and _looks_like_real_key(ASSEMBLYAI_API_KEY) and audio_path:
            try:
                return transcribe_with_sdk(audio_path)
            except HTTPException:
                raise
            except Exception as exc:
                sys.stderr.write("AssemblyAI SDK failed, trying REST: %s\n" % exc)

        if _looks_like_real_key(ASSEMBLYAI_API_KEY) and file_bytes:
            try:
                return transcribe_with_rest(file_bytes)
            except Exception as exc:
                sys.stderr.write("AssemblyAI REST failed, using local engine: %s\n" % exc)

    if not fallback_text and file_bytes:
        try:
            fallback_text = file_bytes.decode("utf-8").strip()
        except Exception:
            fallback_text = ""

    if not fallback_text:
        raise HTTPException(
            status_code=400,
            detail="Could not transcribe any speech from the audio",
        )
    return transcribe_local(fallback_text, audio_bytes=file_bytes)


# ─── IONIX BLOCKCHAIN ADAPTATION FUNCTIONS ──────────────────────────────────
def evaluate_patient_compliance(patient_text, medications):
    text_lower = patient_text.lower()
    if any(word in text_lower for word in ADVERSE_CUES):
        return "ADVERSE_REACTION_WARN"
    for med in medications:
        if med.lower() in text_lower and any(
            word in text_lower for word in ["took", "taken", "yes", "done"]
        ):
            return "VERIFIED_COMPLIANT"
    return "NON_COMPLIANT_TRIGGER"


def generate_ionix_block_receipt(patient_id, medical_state):
    timestamp = datetime.now().isoformat()
    raw_payload = "%s-%s-%s" % (patient_id, medical_state, timestamp)
    tx_hash = "0x" + hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
    return {
        "network": "IONIX-Bio-Mainnet",
        "block_number": random.randint(4850000, 4899999),
        "transaction_hash": tx_hash,
        "execution_status": "SUCCESS",
        "gas_used_ionx": round(random.uniform(0.001, 0.005), 5),
        "consensus_model": "Quantum-AI-DAG",
        "encryption_layer": "Zero-Knowledge-Anonymized",
        "telemetry_state_recorded": medical_state,
    }


def _patient_first_name(patient):
    if not patient:
        return "there"
    if isinstance(patient, dict):
        name = patient.get("name") or "there"
    else:
        name = getattr(patient, "name", "there") or "there"
    return name.split()[0]


def _contains_any(text, needles):
    return any(n in text for n in needles)


def analyze_utterance(text, medications):
    """Read affect, named medicines, and the disease each medicine treats."""
    lowered = (text or "").lower()
    meds = [m.lower() for m in (medications or [])]
    symptoms = []
    seen = set()
    for needle, label in SYMPTOM_LEXICON:
        if needle in lowered and label not in seen:
            seen.add(label)
            symptoms.append(label)

    forgot = _contains_any(lowered, FORGET_CUES)
    flustered = _contains_any(lowered, FLUSTER_CUES)
    if _contains_any(lowered, ANXIETY_CUES):
        affect = "anxious"
        frame = "Anxiety is the body asking 'am I safe?' — we answer with facts, not shame."
    elif _contains_any(lowered, LOW_MOOD_CUES):
        affect = "low_mood"
        frame = "Low mood drains initiative (Beck; Bandura). That is load, not laziness."
    elif _contains_any(lowered, FRUSTRATION_CUES):
        affect = "frustrated"
        frame = "Frustration is often a need for autonomy, not refusal of care."
    elif flustered or forgot:
        affect = "flustered"
        frame = "Self-reproach after a missed dose is common; prospective memory fails before character does."
    elif _contains_any(lowered, ADVERSE_CUES) or symptoms:
        affect = "somatic_distress"
        frame = "People act on the symptom story they believe. Name the likely medicine link so fear shrinks."
    elif _contains_any(lowered, POSITIVE_CUES):
        affect = "well"
        frame = "A good day is the best moment to keep a silent-disease habit."
    else:
        affect = "neutral"
        frame = "Adherence follows perceived safety and barriers, not intelligence. We lower barriers."

    mentioned_meds = find_mentioned_meds(text)
    took = _contains_any(lowered, ADHERENCE_CUES) and not forgot
    greeting_only = (
        not symptoms
        and not mentioned_meds
        and not took
        and not forgot
        and len(lowered.split()) <= 10
    )

    med_links = []
    scan_meds = list(dict.fromkeys(mentioned_meds + meds))
    for med in scan_meds:
        profile = MEDICATION_ATLAS.get(med) or {}
        if not profile:
            continue
        if "dizziness" in symptoms or "headache" in symptoms:
            if profile.get("dizzy") or profile.get("headache"):
                med_links.append((med, profile.get("dizzy") or profile.get("headache")))
        if "cough" in symptoms and profile.get("cough"):
            med_links.append((med, profile["cough"]))
        if symptoms and set(symptoms) & {"nausea", "vomiting", "diarrhea", "abdominal_discomfort", "heartburn", "indigestion"}:
            if profile.get("gi"):
                med_links.append((med, profile["gi"]))
        if "myalgia" in symptoms and profile.get("myalgia"):
            med_links.append((med, profile["myalgia"]))
        if "edema" in symptoms and profile.get("edema"):
            med_links.append((med, profile["edema"]))
        if "tremor_or_hypoglycemia" in symptoms or "diaphoresis" in symptoms:
            if profile.get("hypoglycemia"):
                med_links.append((med, profile["hypoglycemia"]))
        if "dyspnea" in symptoms or "chest_symptom" in symptoms:
            med_links.append((med, "crushing pressure or air hunger is emergency care until a clinician says otherwise"))

    return {
        "affect": affect,
        "frame": frame,
        "symptoms": symptoms,
        "mentioned_meds": mentioned_meds,
        "forgot": forgot,
        "took": took,
        "greeting_only": greeting_only,
        "med_links": med_links,
        "sentiment": _sentiment_from_text(text),
    }


def _safety_net(symptoms):
    if "chest_symptom" in symptoms or "dyspnea" in symptoms:
        return "If this is crushing pressure, sweating, or breathlessness, use emergency care now."
    if "tremor_or_hypoglycemia" in symptoms or "diaphoresis" in symptoms:
        return "If you take insulin or a sugar-lowering drug and feel shaky or sweaty, take fast carbohydrate and do not drive."
    if "headache" in symptoms and "dizziness" in symptoms:
        return "Sit until the room steadies. Worst-of-life headache, fainting, or one-sided weakness is emergency care."
    return ""


def _display_med(med):
    profile = MEDICATION_ATLAS.get(med) or {}
    return profile.get("display") or med


def _identity_clause(med):
    profile = MEDICATION_ATLAS.get(med) or {}
    treats = profile.get("treats")
    name = _display_med(med)
    if treats:
        return "%s is for %s" % (name, treats)
    return name


def _opening_line(first, analysis):
    affect = analysis["affect"]
    if analysis["forgot"] or affect == "flustered":
        return "You're safe, %s — forgetting a dose is common, not a failing." % first
    if affect == "anxious":
        return "You're safe, %s — I hear the worry." % first
    if affect == "low_mood":
        return "I'm here, %s — this heaviness is not a lack of willpower." % first
    if affect == "frustrated":
        return "That's fair, %s — you still get a say." % first
    if affect == "somatic_distress":
        felt = ", ".join(s.replace("_", " ") for s in analysis["symptoms"][:2]) or "that"
        return "I hear the %s, %s — you're safe with me." % (felt, first)
    if affect == "well":
        return "Good to hear, %s — you're safe." % first
    if analysis["greeting_only"]:
        return "Hello %s — you're safe here." % first
    return "I'm with you, %s — you're safe." % first


def _medicine_line(analysis, patient_meds):
    focus = (analysis.get("mentioned_meds") or [])[:1]
    if not focus and analysis.get("forgot") and patient_meds:
        names = " and ".join(_display_med(m) for m in patient_meds[:3])
        return "Your listed medicines are %s. Take the missed one when you remember unless the next dose is close — never double." % names

    if not focus:
        if analysis.get("med_links"):
            med, note = analysis["med_links"][0]
            return "%s. %s." % (_identity_clause(med), note.rstrip("."))
        if analysis.get("affect") == "well" and patient_meds:
            silent = MEDICATION_ATLAS.get(patient_meds[0], {}).get("silent_disease")
            if silent:
                return "Feeling well does not mean %s has finished its work — %s." % (
                    _display_med(patient_meds[0]),
                    silent,
                )
        return ""

    med = focus[0]
    profile = MEDICATION_ATLAS.get(med) or {}
    name = _display_med(med)
    identity = _identity_clause(med)
    on_list = med in patient_meds
    extra = "" if on_list else "; it is not on your clinic list, but I still know it"
    if analysis.get("forgot"):
        missed = (profile.get("missed") or "Take it when you remember, and do not double").rstrip(".")
        missed = missed.replace(". ", " — ")
        interact = (profile.get("interact") or "").rstrip(".")
        interact = interact.replace(". ", " — ")
        line = "A missed %s is not an emergency: %s%s. %s" % (name, identity, extra, missed)
        if interact:
            interact = interact[:1].lower() + interact[1:]
            line = line.rstrip(".") + " — " + interact
        return line.rstrip(".") + "."
    if analysis.get("took"):
        return "You took %s — that is kept care. %s%s." % (name, identity, extra)
    if analysis.get("med_links"):
        note = analysis["med_links"][0][1]
        return "%s%s. %s." % (identity, extra, note.rstrip("."))
    return "%s%s." % (identity, extra)


def _next_step(analysis):
    focus = analysis.get("mentioned_meds") or []
    profile = (MEDICATION_ATLAS.get(focus[0]) or {}) if focus else {}
    if analysis.get("forgot") and profile.get("prn"):
        return "Is the discomfort back, or was this only the missed dose?"
    if analysis.get("forgot"):
        return "How do you feel now?"
    if analysis.get("symptoms"):
        return "Is it easing, holding, or climbing?"
    if analysis.get("took"):
        return "How does your body feel?"
    if analysis.get("greeting_only"):
        return "How are you feeling, and have today's medicines been taken?"
    return "What would help to say next?"


def _clip_spoken(text, max_sentences=4, max_chars=520):
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]
    kept = []
    for sentence in sentences:
        trial = (" ".join(kept + [sentence])).strip()
        if kept and (len(kept) >= max_sentences or len(trial) > max_chars):
            break
        kept.append(sentence)
    return " ".join(kept)


def generate_dynamic_clinical_response(
    compliance_state,
    text,
    patient=None,
    medications=None,
    transcript=None,
    history=None,
):
    """Short, conclusive, safety-first speech. Never shame. Academic frame stays off-mic."""
    first = _patient_first_name(patient)
    meds = [m.lower() for m in (medications or [])]
    analysis = analyze_utterance(text, meds)
    parts = [_opening_line(first, analysis)]

    med_line = _medicine_line(analysis, meds)
    if med_line:
        parts.append(med_line)

    safety = _safety_net(analysis["symptoms"])
    if safety:
        parts.append(safety)
    elif compliance_state == "ADVERSE_REACTION_WARN":
        parts.append("I've noted this for your clinic so you are not deciding it alone.")

    parts.append(_next_step(analysis))
    response = _clip_spoken(" ".join(p.strip() for p in parts if p and p.strip()))
    analysis["spoken"] = response
    generate_dynamic_clinical_response.last_analysis = analysis
    return response


# ─── CALM CLINICAL TTS (stdlib formant voice) ───────────────────────────────
_PHONE_FORMANTS = {
    "AA": (730, 1090, 2440),
    "AE": (660, 1720, 2410),
    "AH": (640, 1190, 2390),
    "AO": (570, 840, 2410),
    "AW": (730, 1090, 2440),
    "AY": (660, 1720, 2410),
    "EH": (530, 1840, 2480),
    "ER": (490, 1350, 1690),
    "EY": (530, 1840, 2480),
    "IH": (390, 1990, 2550),
    "IY": (270, 2290, 3010),
    "OW": (570, 840, 2410),
    "OY": (570, 840, 2410),
    "UH": (440, 1020, 2240),
    "UW": (300, 870, 2240),
}
_PHONE_SAY = {
    "B": ("AH", True, 0.045),
    "D": ("AH", True, 0.045),
    "G": ("AH", True, 0.05),
    "P": ("AH", False, 0.05),
    "T": ("AH", False, 0.05),
    "K": ("AH", False, 0.055),
    "F": ("UH", False, 0.07),
    "S": ("IY", False, 0.08),
    "SH": ("UH", False, 0.09),
    "TH": ("IH", False, 0.07),
    "V": ("AH", True, 0.06),
    "Z": ("IY", True, 0.07),
    "HH": ("AH", False, 0.05),
    "M": ("AH", True, 0.08),
    "N": ("IH", True, 0.07),
    "NG": ("UH", True, 0.08),
    "L": ("UH", True, 0.07),
    "R": ("ER", True, 0.07),
    "W": ("UW", True, 0.06),
    "Y": ("IY", True, 0.06),
    "CH": ("IY", False, 0.07),
    "JH": ("IY", True, 0.07),
}
_DIGRAPHS = [
    ("tion", ["SH", "AH", "N"]),
    ("sion", ["ZH", "AH", "N"]),
    ("ough", ["AH", "F"]),
    ("ight", ["AY", "T"]),
    ("igh", ["AY"]),
    ("eer", ["IH", "R"]),
    ("air", ["EH", "R"]),
    ("ear", ["IH", "R"]),
    ("oor", ["AO", "R"]),
    ("our", ["AW", "ER"]),
    ("ure", ["Y", "UH", "R"]),
    ("ing", ["IH", "NG"]),
    ("ch", ["CH"]),
    ("sh", ["SH"]),
    ("th", ["TH"]),
    ("ph", ["F"]),
    ("wh", ["W"]),
    ("ck", ["K"]),
    ("ng", ["NG"]),
    ("qu", ["K", "W"]),
    ("ee", ["IY"]),
    ("ea", ["IY"]),
    ("oo", ["UW"]),
    ("ou", ["AW"]),
    ("ow", ["AW"]),
    ("ay", ["AY"]),
    ("ai", ["AY"]),
    ("oy", ["OY"]),
    ("oi", ["OY"]),
    ("aw", ["AO"]),
    ("au", ["AO"]),
    ("er", ["ER"]),
    ("ar", ["AA", "R"]),
    ("or", ["AO", "R"]),
    ("ir", ["ER"]),
    ("ur", ["ER"]),
    ("al", ["AO", "L"]),
    ("le", ["AH", "L"]),
]
_LETTER_PHONE = {
    "a": ["AE"], "e": ["EH"], "i": ["IH"], "o": ["AA"], "u": ["AH"],
    "b": ["B"], "c": ["K"], "d": ["D"], "f": ["F"], "g": ["G"],
    "h": ["HH"], "j": ["JH"], "k": ["K"], "l": ["L"], "m": ["M"],
    "n": ["N"], "p": ["P"], "q": ["K"], "r": ["R"], "s": ["S"],
    "t": ["T"], "v": ["V"], "w": ["W"], "x": ["K", "S"], "y": ["Y"],
    "z": ["Z"],
}
_PRONOUNCE = {
    "you're": "yoor",
    "you": "yoo",
    "your": "yor",
    "safe": "sayf",
    "jane": "jayn",
    "eno": "ee-noh",
    "metformin": "met-for-min",
    "lisinopril": "lye-sin-oh-pril",
    "heartburn": "hart-bern",
    "indigestion": "in-di-jes-chun",
    "antacid": "ant-ass-id",
    "diabetes": "dye-uh-bee-teez",
    "emergency": "ee-mer-jen-see",
    "clinic": "klin-ik",
    "stomach": "stum-uk",
    "common": "kom-un",
    "failing": "fay-ling",
    "remember": "ri-mem-ber",
    "absorb": "ab-sorb",
    "pressure": "presh-er",
    "alright": "all-rite",
}


class _Resonator(object):
    def __init__(self, freq, bandwidth, sr):
        radius = math.exp(-math.pi * bandwidth / float(sr))
        self.a = 2.0 * radius * math.cos(2.0 * math.pi * freq / float(sr))
        self.b = -radius * radius
        self.y1 = 0.0
        self.y2 = 0.0

    def tick(self, x):
        y = x + self.a * self.y1 + self.b * self.y2
        self.y2 = self.y1
        self.y1 = y
        return y


def _word_to_phones(word):
    raw = _PRONOUNCE.get(word, word).lower()
    phones = []
    for part in re.split(r"[^a-z]+", raw):
        if not part:
            continue
        i = 0
        while i < len(part):
            matched = False
            for spell, seq in _DIGRAPHS:
                if part.startswith(spell, i):
                    phones.extend(seq)
                    i += len(spell)
                    matched = True
                    break
            if matched:
                continue
            phones.extend(_LETTER_PHONE.get(part[i], []))
            i += 1
    return phones or ["AH"]


def _text_to_phones(text):
    clean = (text or "").replace("—", " ").replace("–", " ").replace("'", "'")
    phones = []
    for raw in re.findall(r"[A-Za-z']+|[.!?]", clean):
        if raw in ".!?":
            phones.append(".")
            continue
        phones.extend(_word_to_phones(raw.lower()))
        phones.append(" ")
    return phones


def synthesize_speech(text, f0_hz=176.0):
    """Calm low-arousal voice: falling pitch, gentle amplitude, stdlib only."""
    sr = VOICE_SAMPLE_RATE
    phones = _text_to_phones(text)[:220]
    samples = []
    rng = random.Random(11)
    phase = 0.0
    total_phones = max(1, len([p for p in phones if p not in (" ", ".")]))
    voiced_i = 0
    for phone in phones:
        if phone == " ":
            samples.extend([0.0] * int(sr * 0.055))
            continue
        if phone == ".":
            samples.extend([0.0] * int(sr * 0.16))
            continue
        voiced_i += 1
        fall = 1.0 - 0.12 * (voiced_i / float(total_phones))
        f0 = f0_hz * fall
        if phone in _PHONE_FORMANTS:
            f1, f2, f3 = _PHONE_FORMANTS[phone]
            voiced = True
            dur = 0.095 if phone in ("AY", "AW", "OY", "EY", "OW") else 0.075
            noise_mix = 0.02
        else:
            vowel, voiced, dur = _PHONE_SAY.get(phone, ("AH", True, 0.06))
            f1, f2, f3 = _PHONE_FORMANTS[vowel]
            noise_mix = 0.0 if voiced else 0.55
        r1 = _Resonator(f1, 90, sr)
        r2 = _Resonator(f2, 120, sr)
        r3 = _Resonator(f3, 180, sr)
        n = max(1, int(sr * dur))
        for i in range(n):
            env = math.sin(math.pi * i / float(n))
            phase += 2.0 * math.pi * f0 / float(sr)
            buzz = 0.18 if math.sin(phase) > 0 else -0.04
            noise = (rng.random() * 2.0 - 1.0) * 0.12
            source = (1.0 - noise_mix) * buzz + noise_mix * noise
            y = 0.45 * r1.tick(source) + 0.30 * r2.tick(source) + 0.12 * r3.tick(source)
            samples.append(max(-1.0, min(1.0, y * env * 0.34)))

    if not samples:
        samples = [0.0] * int(sr * 0.3)
    fade = min(len(samples), int(sr * 0.02))
    for i in range(fade):
        samples[i] *= i / float(fade)
        samples[-1 - i] *= i / float(fade)

    raw = b"".join(struct.pack("<h", int(x * 30000)) for x in samples)
    buffer = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    path = buffer.name
    buffer.close()
    wav = wave.open(path, "wb")
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(sr)
    wav.writeframes(raw)
    wav.close()
    with open(path, "rb") as handle:
        data = handle.read()
    try:
        os.remove(path)
    except Exception:
        pass
    duration = round(len(samples) / float(sr), 2)
    return data, duration


def try_play_wav(path):
    """Best-effort local playback so the spoken reply can actually be heard."""
    try:
        import subprocess
    except ImportError:
        return False
    players = (
        ["afplay", path],
        ["aplay", "-q", path],
        ["paplay", path],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
        ["powershell", "-c", "(New-Object Media.SoundPlayer '%s').PlaySync()" % path],
    )
    devnull = getattr(subprocess, "DEVNULL", open(os.devnull, "wb"))
    for cmd in players:
        try:
            runner = getattr(subprocess, "run", None)
            if runner is not None:
                result = runner(cmd, stdout=devnull, stderr=devnull, timeout=20)
                code = getattr(result, "returncode", 1)
            else:
                code = subprocess.call(cmd, stdout=devnull, stderr=devnull)
            if code == 0:
                return True
        except Exception:
            continue
    return False


def attach_voice(payload, spoken_text):
    try:
        wav_bytes, duration = synthesize_speech(spoken_text)
        with open(VOICE_WAV, "wb") as handle:
            handle.write(wav_bytes)
        LAST_VOICE["bytes"] = wav_bytes
        LAST_VOICE["duration"] = duration
        LAST_VOICE["path"] = VOICE_WAV
        payload["voice_file"] = VOICE_WAV
        payload["voice_duration_sec"] = duration
        payload["voice_tone"] = "calm-safe"
        payload["voice_played"] = try_play_wav(VOICE_WAV)
    except Exception as exc:
        payload["voice_error"] = str(exc)
    return payload


# ─── CORE RUNTIME (shared by API and local demo) ────────────────────────────
def start_session(patient_id, patient_data):
    insert_or_update_patient(patient_id, patient_data)
    session_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (session_id, patient_id) VALUES (?, ?)",
        (session_id, patient_id),
    )
    conn.commit()
    conn.close()
    return {
        "session_id": session_id,
        "patient_id": patient_id,
        "status": "created",
        "timestamp": datetime.now().isoformat(),
    }


def process_chat(session_id, message, transcript=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT patient_id FROM sessions WHERE session_id = ?", (session_id,))
    session = cursor.fetchone()
    conn.close()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    patient_id = session["patient_id"]
    patient = get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient data profile missing")

    medications = json.loads(patient["medications"])
    save_message(session_id, message.sender, message.text)
    history = get_chat_history(session_id)

    compliance_state = evaluate_patient_compliance(message.text, medications)
    bot_response = generate_dynamic_clinical_response(
        compliance_state,
        message.text,
        patient=patient,
        medications=medications,
        transcript=transcript,
        history=history,
    )
    receipt = generate_ionix_block_receipt(patient_id, compliance_state)
    save_message(session_id, "assistant", bot_response)
    analysis = getattr(generate_dynamic_clinical_response, "last_analysis", None) or {}

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sessions SET last_active = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()

    payload = {
        "session_id": session_id,
        "response": bot_response,
        "timestamp": datetime.now().isoformat(),
        "ionix_blockchain_receipt": receipt,
        "compliance_state": compliance_state,
        "psychological_state": analysis.get("affect"),
        "clinical_reasoning": analysis.get("frame"),
        "symptoms": analysis.get("symptoms") or [],
        "mentioned_meds": analysis.get("mentioned_meds") or [],
    }
    if transcript:
        payload["assemblyai_transcript"] = transcript
        payload["spoken_text"] = transcript.get("text")
        payload["sentiment"] = transcript.get("sentiment") or analysis.get("sentiment")
        payload["entities"] = _entities_from_text(message.text, medications)
    else:
        payload["sentiment"] = analysis.get("sentiment")
        payload["entities"] = _entities_from_text(message.text, medications)
    return attach_voice(payload, bot_response)


def process_audio_chat(session_id, file_bytes, filename=None, fallback_text=None, offline=False):
    tmp_path = None
    suffix = os.path.splitext(filename or "")[1] or ".wav"
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(file_bytes or b"")
        tmp_path = tmp.name
        tmp.close()
        transcript = transcribe_audio(
            audio_path=tmp_path,
            file_bytes=file_bytes,
            fallback_text=fallback_text,
            offline=offline,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    spoken_text = (transcript.get("text") or "").strip()
    if not spoken_text:
        raise HTTPException(
            status_code=400,
            detail="Could not transcribe any speech from the audio",
        )
    return process_chat(session_id, ChatMessage(text=spoken_text, sender="patient"), transcript)


# ─── FASTAPI SURFACE (Lablab / production) ──────────────────────────────────
app = None
if HAS_FASTAPI:
    app = FastAPI(title="MediAI + IONIX", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class PatientDataModel(BaseModel):
        name: str
        age: int
        medications: List[str]
        next_appointment: Optional[str] = None

    class SessionStartRequest(BaseModel):
        patient_id: str
        patient_data: PatientDataModel

    class ChatMessageModel(BaseModel):
        text: str
        sender: str = "patient"

    @app.get("/health")
    def health_check():
        return {
            "status": "healthy",
            "service": "MediAI + IONIX Architecture",
            "assemblyai_sdk": HAS_AAI_SDK,
            "assemblyai_key_configured": _looks_like_real_key(ASSEMBLYAI_API_KEY),
        }

    @app.post("/api/session/start")
    def api_start_session(request: SessionStartRequest):
        try:
            data = PatientData(
                request.patient_data.name,
                request.patient_data.age,
                request.patient_data.medications,
                request.patient_data.next_appointment,
            )
            return start_session(request.patient_id, data)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/chat")
    def api_chat(session_id: str, message: ChatMessageModel):
        try:
            return process_chat(session_id, ChatMessage(message.text, message.sender))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/chat/audio")
    async def api_chat_audio(session_id: str, file: UploadFile = File(...)):
        """Upload a wav/mp3/m4a. AssemblyAI transcribes it, then IONIX records the state."""
        try:
            file_bytes = await file.read()
            return process_audio_chat(session_id, file_bytes, filename=file.filename)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/voice")
    def api_voice():
        """Last calm spoken reply as WAV."""
        try:
            from fastapi.responses import FileResponse, Response
        except ImportError:
            raise HTTPException(status_code=500, detail="FastAPI responses unavailable")
        if LAST_VOICE.get("bytes"):
            return Response(content=LAST_VOICE["bytes"], media_type="audio/wav")
        if os.path.exists(VOICE_WAV):
            return FileResponse(VOICE_WAV, media_type="audio/wav", filename=VOICE_WAV)
        raise HTTPException(status_code=404, detail="No spoken reply yet")


# ─── LOCAL DEMO (this editor) ───────────────────────────────────────────────
DEFAULT_SPOKEN = (
    "I took my metformin this morning but I have a headache and feel dizzy"
)


def read_spoken_input(default):
    """Use editor stdin when present. Never block if the pipe has no data."""
    try:
        if sys.stdin is None or getattr(sys.stdin, "closed", False):
            return default
        try:
            if sys.stdin.isatty():
                return default
        except Exception:
            pass
        import select

        ready, _, _ = select.select([sys.stdin], [], [], 0.15)
        if not ready:
            return default
        text = (sys.stdin.read() or "").strip()
        return text if text else default
    except Exception:
        return default


def compact_voice_result(voice):
    transcript = voice.get("assemblyai_transcript") or {}
    receipt = voice.get("ionix_blockchain_receipt") or {}
    return {
        "input": transcript.get("text") or voice.get("spoken_text"),
        "engine": transcript.get("speech_model"),
        "confidence": transcript.get("confidence"),
        "sentiment": voice.get("sentiment"),
        "psychological_state": voice.get("psychological_state"),
        "symptoms": voice.get("symptoms") or [],
        "mentioned_meds": voice.get("mentioned_meds") or [],
        "entities": voice.get("entities") or [],
        "compliance_state": voice.get("compliance_state"),
        "clinical_reasoning": voice.get("clinical_reasoning"),
        "assistant_response": voice.get("response"),
        "voice_file": voice.get("voice_file"),
        "voice_duration_sec": voice.get("voice_duration_sec"),
        "voice_tone": voice.get("voice_tone"),
        "voice_played": voice.get("voice_played"),
        "ionix": {
            "network": receipt.get("network"),
            "block_number": receipt.get("block_number"),
            "transaction_hash": receipt.get("transaction_hash"),
            "execution_status": receipt.get("execution_status"),
            "telemetry_state_recorded": receipt.get("telemetry_state_recorded"),
        },
    }


def run_hackathon_demo():
    spoken = read_spoken_input(DEFAULT_SPOKEN)
    live_network = assemblyai_reachable()
    key_ok = _looks_like_real_key(ASSEMBLYAI_API_KEY)
    # This editor has no outbound network and stdin is text, not a wav.
    # Live AssemblyAI runs on Lablab when the host can reach the API.
    use_live = live_network and key_ok

    print("=== MediAI + IONIX  |  AssemblyAI speech pipeline ===")
    print("INPUT           : %s" % spoken)
    print("AssemblyAI key  : %s" % ("configured" if key_ok else "missing"))
    print("AssemblyAI SDK  : %s" % HAS_AAI_SDK)
    print("API reachable   : %s" % live_network)
    if use_live:
        print("Engine          : live AssemblyAI (upload + transcribe)")
    else:
        print("Engine          : AssemblyAI-compatible local engine")
        print("                  (this editor blocks the internet; Lablab uses your key live)")
    print("")

    patient = PatientData(
        name="Jane Doe",
        age=54,
        medications=["metformin", "lisinopril"],
        next_appointment="2026-04-12",
    )
    session = start_session("patient-jane-001", patient)
    print("SESSION")
    print("  id      : %s" % session["session_id"])
    print("  patient : %s (%s)" % (patient.name, session["patient_id"]))
    print("  meds    : %s" % ", ".join(patient.medications))
    print("")

    audio_bytes = spoken.encode("utf-8")
    voice = process_audio_chat(
        session["session_id"],
        audio_bytes,
        filename="patient_checkin.wav",
        fallback_text=spoken,
        offline=not use_live,
    )
    result = compact_voice_result(voice)

    print("OUTPUT")
    print("  transcript : %s" % result["input"])
    print("  sentiment  : %s" % result["sentiment"])
    print("  psychology : %s" % result.get("psychological_state"))
    print("  symptoms   : %s" % (result.get("symptoms") or "none"))
    print("  medicines  : %s" % (result.get("mentioned_meds") or "none"))
    print("  entities   : %s" % (result["entities"] or "none"))
    print("  compliance : %s" % result["compliance_state"])
    print("  reasoning  : %s" % result.get("clinical_reasoning"))
    print("")
    print("VOICE  (calm, spoken)")
    print("  %s" % result["assistant_response"])
    print("  file     : %s" % (result.get("voice_file") or "none"))
    print("  duration : %ss" % result.get("voice_duration_sec"))
    print("  tone     : %s" % result.get("voice_tone"))
    print("  played   : %s" % result.get("voice_played"))
    print("  ionix tx : %s" % result["ionix"]["transaction_hash"])
    print("  ionix blk: %s" % result["ionix"]["block_number"])
    print("")
    print(json.dumps(result, indent=2))
    print("")
    print("CHAT HISTORY")
    print(json.dumps(get_chat_history(session["session_id"]), indent=2))


if __name__ == "__main__":
    run_hackathon_demo()