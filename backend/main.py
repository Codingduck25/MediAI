from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import sqlite3
import uuid
import json
from typing import Optional, List

app=FastAPI()

# Enables CORS for frontend communication.
app.add_middleware(
    CORSMiddleware,
    allow_origins = ["*"],
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers = ["*"],
)

#Database setup
DB_FILE = "mediai.db"

def init_db():
    """Creates the SQLite database with the required tables"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    #Sessions table
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
        '''
    )

    #Patients table
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            medications TEXT NOT NULL,
            next_appointment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''
    )

    #Chat history table
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS chat_history (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            message TEXT NOT NULL
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
        '''
    )

    conn.commit()
    conn.close()

#Start the db when started.
init_db()

#Pydantic models
class PatientData(BaseModel):
    name : str
    age : int
    medications : List[str]
    next_appointment: Optional[str] = None

class SessionStartRequest(BaseModel):
    patient_id : str
    patient_data : PatientData

class ChatMessage(BaseModel):
    text : str
    sender : str = "patient" #or "assistant"

class ChatResponse(BaseModel):
    session_id : str
    response : str
    timestamp : str

class PatientSummary(BaseModel):
    name : str
    age : str
    medications : List[str]
    next_appontment : Optional[str]

# Helper Functions
def get_db_connection():
    """Gets database connections."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def insert_or_update_patient(patient_id: str, patient_data: PatientData):
    """Insert or update the patient records."""
    conn = get_db_connection()
    cursor = conn.cursor()

    medications_json = json.dumps(patient_data.medications)

    cursor.execute(
        '''INSERT OR REPLACE INTO patients table
        (patient_id, name, age, medications, next_appointment)
        VALUES(?, ?, ?, ?, ?)
        ''', (patient_id, patient_data.name, patient_data.age, medications_json, patient_data.next_appointment)
    )
    
    conn.commit()
    conn.close()

def get_patient(patient_id: str) -> Optional[dict]:
    """Retrieve the patient data."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM patients WHERE patient_id = ?', (patient_id))
    patient = cursor.fetchone()
    conn.close()

    if patient:
        return dict(patient)
    return None

def save_message(session_id: str, sender: str, message: str):
    """Saves the message to chat history."""
    conn = get_db_connection()
    cursor = conn.cursor()

    message_id = str(uuid.uuid4())
    cursor.execute(
        '''
        INSERT INTO chat_history (message_id, session_id, sender, message)
        VALUES (?, ?, ?, ?)
        ''', (message_id, session_id, sender, message)
    )

    conn.commit()
    conn.close()

    return message_id

def get_chat_history(session_id: str) -> List[dict]:
    """Retrives chat history for a session"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        '''
        SELECT sender, message, timestamp FROM chat_history
        WHERE session_id = ?
        ORDER BY timestamp ASC
        ''', (session_id,)
    )

    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return messages