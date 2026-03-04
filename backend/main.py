import os
import json
import uuid
import asyncio
from datetime import datetime
from typing import Optional, List

import boto3
from boto3.dynamodb.conditions import Key
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="KYC Agentic AI Backend")

# Enable CORS for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration (env for Lambda; defaults for local)
S3_BUCKET = os.getenv("KYC_DOCUMENTS_BUCKET", "kyc-documents")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMODB_TABLE = os.getenv("KYC_CASES_TABLE", "KycCases")
SQS_QUEUE_NAME = os.getenv("SQS_QUEUE_NAME", "kyc-submissions")

# Boto3 client kwargs: when running in Lambda (no AWS_ENDPOINT_URL), use role; otherwise use test creds for local
_aws_kwargs = {"region_name": AWS_REGION}

# AWS Clients (Boto3)
s3_client = boto3.client("s3", **_aws_kwargs)
sqs_client = boto3.client("sqs", **_aws_kwargs)
dynamodb = boto3.resource("dynamodb", **_aws_kwargs)

def get_submissions_table():
    table = dynamodb.Table(DYNAMODB_TABLE)
    
    try:
        # Check if table exists
        table.load()
    except Exception:
        print(f"Table {DYNAMODB_TABLE} missing, creating now...")

    return table

class LoginRequest(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    email: str
    role: str
    user_id: str
    status: str = "not_started"
    caseId: Optional[str] = None
    identity: Optional[dict] = None
    kyc_logs: Optional[List[dict]] = None
    document_urls: Optional[dict] = None
    files: Optional[List[dict]] = None
    stages: Optional[dict] = None
    finalDecision: Optional[str] = None

# Mock database for login
USERS = [
    {"user_id": "USR001", "email": "analyst@bank.nl", "password": "password123", "role": "analyst"},
    {"user_id": "USR002", "email": "uploader@bank.nl", "password": "password123", "role": "uploader"}
]

def generate_presigned_urls(s3_paths: dict) -> dict:
    document_urls = {}
    for key, s3_uri in s3_paths.items():
        if s3_uri.startswith("s3://"):
            parts = s3_uri[5:].split("/", 1)
            if len(parts) == 2:
                bucket, s3_key = parts
                try:
                    url = s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': bucket, 'Key': s3_key},
                        ExpiresIn=3600
                    )
                    # Hack for LocalStack in Docker
                    if "localstack:4566" in url:
                        url = url.replace("localstack:4566", "localhost:4566")
                    document_urls[key] = url
                except Exception as e:
                    print(f"Error generating URL for {s3_key}: {e}")
    return document_urls

@app.on_event("startup")
async def startup_event():
    # Increased retries for LocalStack startup
    max_retries = 12
    for i in range(max_retries):
        try:
            # Check S3
            s3_client.list_buckets()
            try:
                s3_client.create_bucket(Bucket=S3_BUCKET)
                print(f"Bucket {S3_BUCKET} created.")
            except Exception as e:
                # print(f"Bucket might exist: {e}")
                pass 
            print(f"Bucket {S3_BUCKET} ready.")

            # Check/Create DynamoDB
            existing_tables = dynamodb.meta.client.list_tables()['TableNames']
            print(f"Existing tables: {existing_tables}")
            
            
            # Final verification
            final_tables = dynamodb.meta.client.list_tables()['TableNames']
            print(f"Final tables check: {final_tables}")
            if DYNAMODB_TABLE in final_tables:
                print("Startup sync complete.")
                # Ensure SQS queue exists
                try:
                    sqs_client.create_queue(QueueName=SQS_QUEUE_NAME)
                    print(f"SQS Queue {SQS_QUEUE_NAME} created/ready.")
                except Exception as e:
                    print(f"Error ensuring SQS queue: {e}")
                break
            else:
                print("Table still missing after creation, retrying...")
                
        except Exception as e:
            print(f"AWS not ready (attempt {i+1}/{max_retries}): {e}")
            await asyncio.sleep(5)
    else:
        print("Failed to initialize AWS resources correctly.")

@app.post("/login", response_model=UserResponse)
async def login(request: LoginRequest):
    user = next((u for u in USERS if u["email"] == request.email and u["password"] == request.password), None)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Check for existing submission using GSI
    submission = None
    try:
        table = get_submissions_table()
        response = table.query(
            IndexName='UserLookupIndex',
            KeyConditionExpression=Key('user_id').eq(user["user_id"])
        )
        items = response.get('Items', [])
        submission = items[0] if items else None
    except Exception as e:
        # Gracefully handle missing table or index
        print(f"Note: Could not query submissions (table might not be ready): {e}")
        try:
            tables = dynamodb.meta.client.list_tables()['TableNames']
            print(f"Debug - Available tables during login: {tables}")
        except:
            pass
        submission = None
    
    login_status = "not_started"
    case_id = None
    identity = None
    kyc_logs = None
    document_urls = None
    stages = None
    final_decision = None
    
    if submission:
        login_status = submission.get("status", "PENDING")
        # DynamoDB primary key is CaseId (support older items with caseId too)
        case_id = submission.get("CaseId") or submission.get("caseId")
        identity = submission.get("identity")
        stages = submission.get("stages")
        final_decision = submission.get("finalDecision")
        
        kyc_logs = [
            {"time": "14:32:01", "event": "Document upload complete", "agent": "Uploader"},
            {"time": "14:32:15", "event": "OCR extraction started", "agent": "Extraction-Bot"},
            {"time": "14:33:45", "event": "Identity verified via MRZ", "agent": "Identity-Verify-Agent"},
            {"time": "14:34:20", "event": "Sanctions check passed", "agent": "Compliance-Bot"},
            {"time": "14:35:10", "event": "Risk scoring initiated", "agent": "Scoring-Agent"}
        ]

        files_list = submission.get("files", [])
        document_urls = {}
        for f in files_list:
            s3_key = f.get("key")
            if s3_key:
                try:
                    url = s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': f.get("bucket", S3_BUCKET), 'Key': s3_key},
                        ExpiresIn=3600
                    )
                    if "localstack:4566" in url:
                        url = url.replace("localstack:4566", "localhost:4566")
                    document_urls[f.get("type")] = url
                    f["url"] = url # Add URL to the file object itself
                except Exception as e:
                    print(f"Error generating URL for {s3_key}: {e}")

    return {
        "email": user["email"], 
        "role": user["role"],
        "user_id": user["user_id"],
        "status": login_status,
        "caseId": case_id,
        "identity": identity,
        "kyc_logs": kyc_logs,
        "document_urls": document_urls,
        "files": submission.get("files") if submission else None,
        "stages": stages,
        "finalDecision": final_decision
    }

@app.get("/submission/{userId}")
async def get_submission(userId: str):
    try:
        table = get_submissions_table()
        response = table.query(
            IndexName='UserLookupIndex',
            KeyConditionExpression=Key('user_id').eq(userId)
        )
        items = response.get('Items', [])
        if not items:
            return {"status": "not_found"}
        
        submission = items[0]
        
        # Generate pre-signed URLs
        document_urls = {}
        if "files" in submission:
            for f in submission["files"]:
                s3_key = f.get("key")
                if s3_key:
                    try:
                        url = s3_client.generate_presigned_url(
                            'get_object',
                            Params={'Bucket': f.get("bucket", S3_BUCKET), 'Key': s3_key},
                            ExpiresIn=3600
                        )
                        if "localstack:4566" in url:
                            url = url.replace("localstack:4566", "localhost:4566")
                        document_urls[f.get("type")] = url
                    except Exception:
                        pass
        
        return {
            "status": submission.get("status"),
            "caseId": submission.get("CaseId") or submission.get("caseId"),
            "stages": submission.get("stages"),
            "finalDecision": submission.get("finalDecision"),
            "document_urls": document_urls
        }
    except Exception as e:
        print(f"Error fetching submission: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch submission: {str(e)}")

@app.post("/submit-kyc")
async def submit_kyc(
    userId: str = Form(...),
    fullName: str = Form(...),
    address: str = Form(...),
    passportNumber: str = Form(...),
    passportExpiry: str = Form(...),
    dateOfBirth: str = Form("1990-01-01"),
    nationality: str = Form("NL"),
    id_file: UploadFile = File(...),
    address_file: UploadFile = File(...),
    income_file: UploadFile = File(...)
):
    case_id = f"CASE-{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    files_to_upload = {
        "passport": id_file,
        "address": address_file,
        "income": income_file
    }
    
    uploaded_files = []
    
    try:
        # 1. Upload to S3
        for doc_type, file in files_to_upload.items():
            s3_key = f"cases/{case_id}/{doc_type}_{file.filename}"
            s3_client.upload_fileobj(file.file, S3_BUCKET, s3_key)
            uploaded_files.append({
                "type": doc_type,
                "bucket": S3_BUCKET,
                "key": s3_key
            })

        # 2. Build New Submission Structure
        submission_data = {
            # DynamoDB PK must be CaseId
            "CaseId": case_id,
            "createdAt": timestamp,
            "createdBy": f"user-{userId}",
            "user_id": userId,
            "status": "INITIATED",
            "statusUpdatedAt": timestamp,
            "type": "Individual",
            "files": uploaded_files,
            "identity": {
                "fullName": fullName,
                "dateOfBirth": dateOfBirth,
                "nationality": nationality,
                "address": address,
                "passportNumber": passportNumber,
                "passportExpiry": passportExpiry
            }
        }
        
        print(f"DEBUG: Processing submission for user {userId}")
        print(f"DEBUG: Form data: fullName={fullName}, address={address}, passport={passportNumber}, expiry={passportExpiry}, dob={dateOfBirth}, nationality={nationality}")
        print(f"DEBUG: Files: id={id_file.filename}, addr={address_file.filename}, inc={income_file.filename}")
        
        table = get_submissions_table()
        try:
            # Final check of tables before PutItem
            all_tables = dynamodb.meta.client.list_tables()['TableNames']
            print(f"DEBUG: Tables found immediately before PutItem: {all_tables}")
            
            table.put_item(Item=submission_data)
            print(f"DEBUG: PutItem successful for {case_id}")
        except Exception as e:
            print(f"PutItem failed for {case_id}: {e}")
            tables = dynamodb.meta.client.list_tables()['TableNames']
            print(f"Debug - Available tables during ERROR: {tables}")
            raise e

        # 3. Emit event to SQS
        try:
            queue_url_response = sqs_client.get_queue_url(QueueName=SQS_QUEUE_NAME)
            queue_url = queue_url_response['QueueUrl']
            
            sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({
                    "caseId": case_id,
                    "userId": userId,
                    "fullName": fullName,
                    "timestamp": timestamp,
                    "status": "PROCESSING"
                })
            )
            print(f"DEBUG: SQS message sent for {case_id}")
        except Exception as e:
            print(f"DEBUG: Failed to send SQS message: {e}")

        return {
            "status": "success",
            "caseId": case_id,
            "message": "KYC submitted successfully",
            "data": submission_data
        }
    except Exception as e:
        print(f"Submission error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process KYC: {str(e)}")

@app.get("/submissions")
async def get_submissions():
    try:
        table = get_submissions_table()
        # Use SubmissionsByTimeIndex to get all submissions of type 'Individual' sorted by createdAt
        response = table.query(
            IndexName='SubmissionsByTimeIndex',
            KeyConditionExpression=Key('type').eq('Individual'),
            ScanIndexForward=False # Sort descending by createdAt
        )
        submissions = response.get('Items', [])
        
        for document in submissions:
            # Generate pre-signed URLs for documents in new structure
            document["document_urls"] = {}
            if "files" in document:
                for f in document["files"]:
                    s3_key = f.get("key")
                    if s3_key:
                        try:
                            url = s3_client.generate_presigned_url(
                                'get_object',
                                Params={'Bucket': f.get("bucket", S3_BUCKET), 'Key': s3_key},
                                ExpiresIn=3600
                            )
                            if "localstack:4566" in url:
                                url = url.replace("localstack:4566", "localhost:4566")
                            document["document_urls"][f.get("type")] = url
                            f["url"] = url
                        except Exception as e:
                            print(f"Error generating URL for {s3_key}: {e}")
            
        return submissions
    except Exception as e:
        print(f"Error fetching submissions: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch submissions")

@app.get("/analytics/summary")
async def get_analytics_summary():
    try:
        # Note: DynamoDB doesn't have an efficient count everything without a scan or GSI
        # For simplicity in this mock, we'll scan (not recommended for production at scale)
        table = get_submissions_table()
        response = table.scan()
        submissions = response.get('Items', [])
        
        total = len(submissions)
        pending = len([s for s in submissions if s.get("status") == "PROCESSING"])
        auto_approved = len([s for s in submissions if s.get("finalDecision") == "APPROVED"])
        escalations = len([s for s in submissions if s.get("status") == "ESCALATED"])
        
        # In new structure, time recording is different, using mock for now
        avg_time = 252000 
        
        return {
            "total_onboardings": total,
            "pending_review": pending,
            "auto_approved": auto_approved,
            "avg_processing_time": round(avg_time / 1000, 1),
            "escalations": escalations
        }
    except Exception as e:
        print(f"Error fetching analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch analytics")

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# Lambda handler for API Gateway (Mangum wraps FastAPI ASGI app)
try:
    from mangum import Mangum
    handler = Mangum(app, lifespan="off")
except ImportError:
    handler = None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
