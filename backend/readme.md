# Use the project venv so the same Python runs the server (avoid ModuleNotFoundError).
# From repo root: source .venv/Scripts/activate  (or .venv/bin/activate on Unix)
# Then install with the venv's pip:
python -m pip install -r requirements.txt
# Run from the backend directory:
python -m uvicorn main:app --reload --port 8000

http://127.0.0.1:8000/docs



MongoDB:

docker exec -it mongodb mongosh

Once inside the shell, you can run these commands:

show dbs — See all databases.
use kyc_db — Switch to your app's database.
show collections — See your collections (e.g., submissions).
db.submissions.find() — See all records in the submissions collection.
exit — To leave the shell.