# Mock Signicat Assure API

This is a dummy FastAPI application that mimics the Signicat Assure API. It's designed to be used for local development and testing purposes.

## Features

- **Session Management**: Create and track verification sessions.
- **Document Upload**: Mock ID document uploads (e.g., Passport).
- **Biometric Upload**: Mock biometric data uploads (e.g., Selfie).
- **AWS Lambda Ready**: Uses `Mangum` for easy deployment to AWS Lambda.

## Getting Started

### Prerequisites

- Python 3.8+
- Pip

### Installation

1. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Running Locally

1. Start the FastAPI server:
   ```bash
   python app.py
   ```
   Or using uvicorn:
   ```bash
   uvicorn app:app --reload --port 8000
   ```

2. Access the Swagger UI:
   Navigate to `http://localhost:8000/docs` in your browser to explore and test the API.

## API Endpoints

- `POST /sessions`: Create a new verification session.
- `GET /sessions/{sessionId}`: Retrieve the current status and data of a session.
- `POST /sessions/{sessionId}/documents`: Upload a mock ID document.
- `POST /sessions/{sessionId}/biometrics`: Upload mock biometric data.

## Testing

You can use the provided test script to verify the full flow:
```bash
python test_mock_api.py
```
*(Ensure the server is running before executing the test script)*

## Disclaimer

This is a **mock** service and does not perform any real identity verification. It is intended for development and testing only.
