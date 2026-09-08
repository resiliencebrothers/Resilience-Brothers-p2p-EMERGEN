"""Helper CLI: check|reset employee state via MongoDB."""
import os, sys, json, ast
for line in open("/app/backend/.env"):
    if line.startswith("MONGO_URL="): os.environ["MONGO_URL"] = line.split("=",1)[1].strip().strip('"')
    elif line.startswith("DB_NAME="): os.environ["DB_NAME"] = line.split("=",1)[1].strip().strip('"')
from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

cmd = sys.argv[1]
if cmd == "check":
    u = db.users.find_one({"user_id":"user_test_employee01"})
    print(json.dumps({"perms": u.get("allowed_permissions"), "curs": u.get("allowed_currencies")}))
elif cmd == "reset":
    perms = ast.literal_eval(sys.argv[2])  # e.g. "['support']" or "None"
    curs = ast.literal_eval(sys.argv[3])
    db.users.update_one({"user_id":"user_test_employee01"},
        {"$set": {"allowed_permissions": perms, "allowed_currencies": curs}})
    print("ok")
