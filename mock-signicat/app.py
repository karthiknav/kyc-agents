import uuid
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from mangum import Mangum

app = FastAPI(title="Mock Signicat Assure API")

# In-memory storage for mock sessions
sessions = {}

class CreateSessionRequest(BaseModel):
    flow: str = "default"
    language: str = "en"
    externalReference: Optional[str] = None

class SessionResponse(BaseModel):
    id: str
    url: str
    status: str

class DocumentMetadata(BaseModel):
    type: str
    country: str

class DocumentUploadRequest(BaseModel):
    document: str  # Base64 encoded document
    metadata: DocumentMetadata

class BiometricUploadRequest(BaseModel):
    biometric: str  # Base64 encoded biometric data (e.g., selfie)

@app.post("/sessions", response_model=SessionResponse)
async def create_session(request: CreateSessionRequest):
    session_id = str(uuid.uuid4())
    status = "PENDING"
    if request.externalReference == "FORCE_FAIL":
        status = "FAILED"
        
    session = {
        "id": session_id,
        "url": f"https://mock.signicat.com/verify/{session_id}",
        "status": status,
        "documents": [],
        "biometrics": []
    }
    sessions[session_id] = session
    return SessionResponse(id=session_id, url=session["url"], status=session["status"])

@app.get("/sessions/{sessionId}")
async def get_session(sessionId: str):
    if sessionId not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[sessionId]

@app.post("/sessions/{sessionId}/documents")
async def upload_document(sessionId: str, request: DocumentUploadRequest):
    if sessionId not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    doc_status = "UPLOADED"
    if "fail" in request.document.lower():
        sessions[sessionId]["status"] = "FAILED"
        doc_status = "REJECTED"

    sessions[sessionId]["documents"].append({
        "type": request.metadata.type,
        "country": request.metadata.country,
        "status": doc_status
    })
    
    # Simulate verification progress if not failed
    if sessions[sessionId]["status"] != "FAILED":
        if len(sessions[sessionId]["documents"]) > 0 and len(sessions[sessionId]["biometrics"]) > 0:
            sessions[sessionId]["status"] = "SUCCESS"
        
    return {"message": "Document processed", "status": doc_status}

@app.post("/sessions/{sessionId}/biometrics")
async def upload_biometric(sessionId: str, request: BiometricUploadRequest):
    if sessionId not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    bio_status = "UPLOADED"
    if "fail" in request.biometric.lower():
        sessions[sessionId]["status"] = "FAILED"
        bio_status = "REJECTED"

    sessions[sessionId]["biometrics"].append({
        "status": bio_status
    })
    
    # Simulate verification progress if not failed
    if sessions[sessionId]["status"] != "FAILED":
        if len(sessions[sessionId]["documents"]) > 0 and len(sessions[sessionId]["biometrics"]) > 0:
            sessions[sessionId]["status"] = "SUCCESS"
        
    return {"message": "Biometric data processed", "status": bio_status}

# AWS Lambda Handler
handler = Mangum(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
