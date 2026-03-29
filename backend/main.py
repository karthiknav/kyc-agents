import logging
import os
import json
import uuid
import asyncio
from datetime import datetime
from typing import Optional, List

import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key, Attr
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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
# SQS: queue name (use get_queue_url to resolve URL when sending). From SQS_QUEUE_NAME or derived from KYC_INITIATED_QUEUE_ARN.
SQS_QUEUE_NAME = os.getenv("SQS_QUEUE_NAME") or os.getenv("KYC_INITIATED_QUEUE_NAME")
_queue_arn = os.getenv("KYC_INITIATED_QUEUE_ARN", "")
if not SQS_QUEUE_NAME and _queue_arn.startswith("arn:aws:sqs:"):
    _parts = _queue_arn.split(":", 5)
    if len(_parts) >= 6:
        SQS_QUEUE_NAME = _parts[5]

# Boto3 client kwargs: when running in Lambda (no AWS_ENDPOINT_URL), use role; otherwise use test creds for local
_aws_kwargs = {"region_name": AWS_REGION}

# AWS Clients (Boto3)
s3_client = boto3.client("s3", **_aws_kwargs)
sqs_client = boto3.client("sqs", **_aws_kwargs)
dynamodb = boto3.resource("dynamodb", **_aws_kwargs)

def get_submissions_table():
    """Return the KYC cases DynamoDB table. Lambda needs dynamodb:Scan (and Get/Put/Update/Query/BatchGetItem)."""
    return dynamodb.Table(DYNAMODB_TABLE)


def _get_sqs_queue_url() -> str:
    """Resolve SQS QueueUrl from queue name. IAM needs sqs:GetQueueUrl and sqs:SendMessage (no DescribeQueue)."""
    if not SQS_QUEUE_NAME or not SQS_QUEUE_NAME.strip():
        raise ValueError(
            "SQS_QUEUE_NAME (or KYC_INITIATED_QUEUE_NAME / KYC_INITIATED_QUEUE_ARN) is not set. "
            "Set SQS_QUEUE_NAME in the API Lambda environment."
        )
    try:
        resp = sqs_client.get_queue_url(QueueName=SQS_QUEUE_NAME.strip())
        return resp["QueueUrl"]
    except ClientError as e:
        err_code = e.response.get("Error", {}).get("Code", "")
        if err_code in ("AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist"):
            logger.error("SQS queue does not exist: %s", SQS_QUEUE_NAME)
            raise ValueError(f"SQS queue '{SQS_QUEUE_NAME}' does not exist. Create the queue or fix the name.") from e
        if err_code == "AccessDeniedException":
            logger.error("SQS GetQueueUrl denied. Ensure the Lambda role has sqs:GetQueueUrl and sqs:SendMessage.")
        raise
    except Exception as e:
        logger.exception("SQS get_queue_url failed for queue %s", SQS_QUEUE_NAME)
        raise

class LoginRequest(BaseModel):
    email: str
    password: str

class S3Location(BaseModel):
    bucket: str
    key: str

class DocumentProcessingStage(BaseModel):
    result: str = "PENDING"
    summary: str = "Awaiting document processing"
    discrepancies: List[str] = []
    governmentVerificationSummary: str = ""
    reportS3: Optional[S3Location] = None
    updatedAt: Optional[str] = None

class ScreeningResult(BaseModel):
    result: Optional[str] = None
    summary: Optional[str] = None
    updatedAt: Optional[str] = None
    reportS3: Optional[S3Location] = None
    rawResponseS3: Optional[S3Location] = None

class AdverseMediaResult(ScreeningResult):
    searchQueries: Optional[List[str]] = None

class RiskListResult(ScreeningResult):
    datasetsMatched: Optional[List[str]] = None
    pepStatus: Optional[str] = None
    sanctionsStatus: Optional[str] = None

class ScreeningStage(BaseModel):
    status: str = "PENDING"
    summary: str = "Awaiting risk and adverse media screening"
    updatedAt: Optional[str] = None
    reportS3: Optional[S3Location] = None
    adverseMedia: AdverseMediaResult = AdverseMediaResult(
        result="PENDING", 
        summary="Awaiting adverse media search",
        searchQueries=[]
    )
    riskListScreening: RiskListResult = RiskListResult(
        result="PENDING", 
        summary="Awaiting risk list check",
        datasetsMatched=[],
        pepStatus="UNKNOWN",
        sanctionsStatus="UNKNOWN"
    )

class OrchestratorStage(BaseModel):
    status: str = "INITIATED"
    decision: str = "PENDING"
    reason: List[str] = []
    recommendation_summary: str = "Case initiated and awaiting agent analysis"
    decidedAt: Optional[str] = None

class CaseStages(BaseModel):
    documentProcessing: DocumentProcessingStage = DocumentProcessingStage()
    screening: ScreeningStage = ScreeningStage()
    orchestrator: OrchestratorStage = OrchestratorStage()

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
    stages: Optional[CaseStages] = None
    finalDecision: Optional[str] = None

class StatusUpdateRequest(BaseModel):
    status: str

# Mock database for login
USERS = [
    {"user_id": "USR001", "email": "uploader@bank.nl", "password": "password123", "role": "uploader"},
    {"user_id": "USR002", "email": "uploader2@bank.nl", "password": "password123", "role": "uploader"},
    {"user_id": "USR003", "email": "uploader3@bank.nl", "password": "password123", "role": "uploader"},
    {"user_id": "USR004", "email": "uploader4@bank.nl", "password": "password123", "role": "uploader"},
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
                    logger.warning("Error generating URL for %s: %s", s3_key, e)
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
                logger.info("Bucket %s created.", S3_BUCKET)
            except Exception as e:
                logger.debug("Bucket might already exist: %s", e) 
            logger.info("Bucket %s ready.", S3_BUCKET)

            # Check/Create DynamoDB
            existing_tables = dynamodb.meta.client.list_tables()['TableNames']
            logger.info("Existing tables: %s", existing_tables)
            
            
            # Final verification
            final_tables = dynamodb.meta.client.list_tables()['TableNames']
            logger.info("Final tables check: %s", final_tables)
            if DYNAMODB_TABLE in final_tables:
                logger.info("Startup sync complete.")
                # Ensure SQS queue exists (only if queue name is configured)
                if SQS_QUEUE_NAME:
                    try:
                        sqs_client.create_queue(QueueName=SQS_QUEUE_NAME)
                        logger.info("SQS Queue %s created/ready.", SQS_QUEUE_NAME)
                    except Exception as e:
                        logger.warning("Error ensuring SQS queue: %s", e)
                break
            else:
                logger.info("Table still missing after creation, retrying...")
                
        except Exception as e:
            logger.warning("AWS not ready (attempt %s/%s): %s", i + 1, max_retries, e)
            await asyncio.sleep(5)
    else:
        logger.error("Failed to initialize AWS resources correctly.")

@app.post("/login", response_model=UserResponse)
async def login(request: LoginRequest):
    user = next((u for u in USERS if u["email"] == request.email and u["password"] == request.password), None)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Find case for this user (KYC cases table only; no GSI — use Scan with filter)
    submission = None
    try:
        table = get_submissions_table()
        response = table.scan(FilterExpression=Attr("user_id").eq(user["user_id"]))
        items = response.get("Items", [])
        while response.get("LastEvaluatedKey"):
            response = table.scan(
                FilterExpression=Attr("user_id").eq(user["user_id"]),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
        submission = items[0] if items else None
    except Exception as e:
        logger.info("Could not look up submission: %s", e)
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
                    logger.warning("Error generating URL for %s: %s", s3_key, e)

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
        response = table.scan(FilterExpression=Attr("user_id").eq(userId))
        items = response.get("Items", [])
        while response.get("LastEvaluatedKey"):
            response = table.scan(
                FilterExpression=Attr("user_id").eq(userId),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
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
        logger.exception("Error fetching submission")
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
            },
            "stages": CaseStages().dict()
        }
        
        logger.info("Processing submission for user %s", userId)
        logger.debug(
            "Form data: fullName=%s, address=%s, passport=%s, expiry=%s, dob=%s, nationality=%s",
            fullName, address, passportNumber, passportExpiry, dateOfBirth, nationality,
        )
        logger.debug("Files: id=%s, addr=%s, inc=%s", id_file.filename, address_file.filename, income_file.filename)
        
        table = get_submissions_table()
        table.put_item(Item=submission_data)

        # 3. Emit event to SQS (queue URL from ARN or queue name)
        try:
            queue_url = _get_sqs_queue_url()
            logger.info("Sending SQS message to queue %s", queue_url)
            sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({
                    "caseId": case_id,
                    "userId": userId,
                    "fullName": fullName,
                    "timestamp": timestamp,
                    "status": "INITIATED",
                }),
            )
            logger.info("SQS message sent for case %s", case_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to send message to SQS: {str(e)}")

        return {
            "status": "success",
            "caseId": case_id,
            "message": "KYC submitted successfully",
            "data": submission_data
        }
    except Exception as e:
        logger.exception("Submission error")
        raise HTTPException(status_code=500, detail=f"Failed to process KYC: {str(e)}")

@app.get("/submissions")
async def get_submissions():
    try:
        table = get_submissions_table()
        # No GSI: scan KYC cases table for type='Individual', then sort by createdAt
        response = table.scan(FilterExpression=Attr("type").eq("Individual"))
        items = response.get("Items", [])
        while response.get("LastEvaluatedKey"):
            response = table.scan(
                FilterExpression=Attr("type").eq("Individual"),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
        submissions = sorted(
            items,
            key=lambda x: x.get("createdAt") or "",
            reverse=True,
        )
        
        for document in submissions:
            # Explicitly include caseId (lowercase) for frontend compatibility
            if "CaseId" in document and "caseId" not in document:
                document["caseId"] = document["CaseId"]
                
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
                            logger.warning("Error generating URL for %s: %s", s3_key, e)
            
        return submissions
    except Exception as e:
        logger.exception("Error fetching submissions")
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
        logger.exception("Error fetching analytics")
        raise HTTPException(status_code=500, detail="Failed to fetch analytics")

@app.patch("/submissions/{caseId}/status")
async def update_submission_status(caseId: str, request: StatusUpdateRequest):
    try:
        timestamp = datetime.utcnow().isoformat() + "Z"
        table = get_submissions_table()
        
        # 1. Update status in DynamoDB
        table.update_item(
            Key={'CaseId': caseId},
            UpdateExpression="SET #s = :s, statusUpdatedAt = :t",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':s': request.status,
                ':t': timestamp
            }
        )
        return {"status": "success", "message": f"Status updated to {request.status}"}
    except Exception as e:
        logger.exception("Error updating status")
        raise HTTPException(status_code=500, detail=f"Failed to update status: {str(e)}")

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
