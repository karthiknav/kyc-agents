import requests
import json
import base64

BASE_URL = "http://localhost:8080"

def test_positive_flow():
    print("--- Testing Positive Flow ---")
    print("1. Creating session...")
    response = requests.post(f"{BASE_URL}/sessions", json={"flow": "default"})
    session_data = response.json()
    session_id = session_data["id"]
    print(f"Session ID: {session_id}")

    print("2. Uploading ID document...")
    doc_payload = {
        "document": base64.b64encode(b"valid-doc").decode("utf-8"),
        "metadata": {"type": "PASSPORT", "country": "NOR"}
    }
    requests.post(f"{BASE_URL}/sessions/{session_id}/documents", json=doc_payload)

    print("3. Uploading Biometric data...")
    bio_payload = {"biometric": base64.b64encode(b"valid-bio").decode("utf-8")}
    requests.post(f"{BASE_URL}/sessions/{session_id}/biometrics", json=bio_payload)

    print("4. Final status check...")
    response = requests.get(f"{BASE_URL}/sessions/{session_id}")
    status = response.json()["status"]
    print(f"Final Status: {status}")
    assert status == "SUCCESS"
    print("Positive flow PASS\n")

def test_negative_flow_forced():
    print("--- Testing Negative Flow (Forced Failure) ---")
    print("1. Creating session with FORCE_FAIL...")
    response = requests.post(f"{BASE_URL}/sessions", json={"externalReference": "FORCE_FAIL"})
    session_id = response.json()["id"]
    
    print("2. Status check...")
    status = requests.get(f"{BASE_URL}/sessions/{session_id}").json()["status"]
    print(f"Status: {status}")
    assert status == "FAILED"
    print("Forced failure flow PASS\n")

def test_negative_flow_data():
    print("--- Testing Negative Flow (Data-driven Failure) ---")
    print("1. Creating session...")
    response = requests.post(f"{BASE_URL}/sessions", json={})
    session_id = response.json()["id"]

    print("2. Uploading document with 'fail' string...")
    doc_payload = {
        "document": base64.b64encode(b"this content will fail").decode("utf-8"),
        "metadata": {"type": "ID_CARD", "country": "NOR"}
    }
    requests.post(f"{BASE_URL}/sessions/{session_id}/documents", json=doc_payload)

    print("3. Final status check...")
    status = requests.get(f"{BASE_URL}/sessions/{session_id}").json()["status"]
    print(f"Final Status: {status}")
    assert status == "FAILED"
    print("Data-driven failure flow PASS\n")

if __name__ == "__main__":
    try:
        test_positive_flow()
        test_negative_flow_forced()
        test_negative_flow_data()
        print("All tests completed successfully!")
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure the mock API is running on http://localhost:8080")
