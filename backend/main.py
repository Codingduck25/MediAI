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
            patient_id TEXT NOT NULL,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
            message TEXT NOT NULL,
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
    next_appointment : Optional[str]

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
        '''INSERT OR REPLACE INTO patients 
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

    cursor.execute('SELECT * FROM patients WHERE patient_id = ?', (patient_id,))
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

# API Endpoints

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return{"status": "healthy", "service": "MediAI Backend"}

@app.post("/api/session/start")
def start_session(request: SessionStartRequest):
    """
    Create a new session for a patient

    Request body:
    {
        "patient_id": "patient_123"
        "patient_data": {
            "name": "John Doe",
            "age": 65,
            "medications": ["Metformin", "Aspirin"],
            "next_appointment": "2026-09-25 10:00 AM"
        }
    }
    """

    try:
        #Create or update a patient record
        insert_or_update_patient(request.patient_id, request.patient_data)

        #Creating a new session
        session_id = str(uuid.uuid4())
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            INSERT INTO sessions (session_id, patient_id)
            VALUES (?, ?)
            ''', (session_id, request.patient_id)
        )

        conn.commit()
        conn.close()

        return {
            "session_id": session_id,
            "patient_id": request.patient_id,
            "status": "created",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code= 500, detail=str(e))

@app.post("/api/chat")
def chat(session_id: str, message: ChatMessage):
    """
    Sends a message to the AI and receives a response.

    Query Params:
    -session_id: The session ID

    Request body:
    {
        "text": "I have a headache",
        "sender": "patient"
    }
    """
    try:
        #Verify if the session exists
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM sessions WHERE session_id = ?', (session_id,))
        session = cursor.fetchone()
        conn.close()

        if not session:
            raise HTTPException(status_code= 404, detail= "Session not found")

        #To save user message
        save_message(session_id, message.sender, message.text) 

        #Just a placeholder for now
        ai_response = generate_dummy_response(message.text)

        #To save assistant response
        save_message(session_id, "assistant", ai_response)

        return ChatResponse(
            session_id= session_id,
            response = ai_response,
            timestamp = datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code= 500, detail= str(e))

@app.get("/api/patient/{session_id}")
def get_patient_summary(session_id: str):
    """
    Gets patient data for a session

    Return patient summary with name, age, medication and next appointment
    """
    try:
        #Gets the session
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT patient_id FROM sessions WHERE session_id = ?', (session_id,))
        session = cursor.fetchone()
        conn.close()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get patient data
        patient = get_patient(session['patient_id'])
        
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        
        return {
            "name": patient['name'],
            "age": patient['age'],
            "medications": json.loads(patient['medications']),
            "next_appointment": patient['next_appointment']
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))  
@app.get("/api/chat/{session_id}")
def get_conversation_history(session_id: str):
    """
    Retrieve full conversation history for a session
    """
    try:
        # Verify session exists
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM sessions WHERE session_id = ?', (session_id,))
        session = cursor.fetchone()
        conn.close()
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get chat history
        history = get_chat_history(session_id)
        
        return {
            "session_id": session_id,
            "messages": history
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions")
def list_active_sessions():
    """
    List all active sessions (useful for admin/testing)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM sessions WHERE status = "active" ORDER BY created_at DESC')
        sessions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Dummy response generator (placeholder for AI logic)
def generate_dummy_response(user_message: str) -> str:
    """
    Generate a dummy response based on keywords
    This will be replaced with actual AI conversation logic from Abubakar
    """
    user_lower = user_message.lower()
    
    if any(word in user_lower for word in ["appointment", "book", "schedule"]):
        return "I'll help you book an appointment. Can you tell me which day works best for you?"
    elif any(word in user_lower for word in ["medication", "medicine", "dose"]):
        return "I see you're asking about medications. Let me pull up your current prescriptions."
    elif any(word in user_lower for word in ["side effect", "feel", "symptom"]):
        return "Thank you for letting me know. Let me check if this is a common side effect and when you should contact your doctor."
    elif any(word in user_lower for word in ["headache", "pain", "hurt"]):
        return "I'm sorry to hear you're experiencing discomfort. Can you describe the severity on a scale of 1-10?"
    else:
        return "I understand. Could you tell me more about how you're feeling today?"
 
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)