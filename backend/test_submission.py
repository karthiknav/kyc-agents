import requests
import os

API_URL = "http://localhost:8000/submit-kyc"

def test_submission():
    # Create dummy files
    files = {}
    for name in ['id_file', 'address_file', 'income_file', 'selfie_file']:
        with open(f"test_{name}.txt", "w") as f:
            f.write(f"Sample content for {name}")
        files[name] = open(f"test_{name}.txt", "rb")

    data = {
        "fullName": "Test User",
        "address": "456 LocalStack Lane",
        "passportNumber": "TEST999",
        "passportExpiry": "2030-01-01"
    }

    try:
        print(f"Sending request to {API_URL}...")
        response = requests.post(API_URL, data=data, files=files)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Close files and cleanup
        for f in files.values():
            f.close()
        for name in ['id_file', 'address_file', 'income_file', 'selfie_file']:
            os.remove(f"test_{name}.txt")

if __name__ == "__main__":
    test_submission()
