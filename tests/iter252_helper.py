"""iter252 helper CLI: manipulate user_test_employee01 for the revert-template test.

Usage:
  python iter252_helper.py check
  python iter252_helper.py reset_all              # perms=['support'] curs=['USD'] $unset applied_templates
  python iter252_helper.py set_curs '["EUR"]'
  python iter252_helper.py restore                # allowed_permissions=None allowed_currencies=[] $unset applied_templates
"""
import os, sys, json, ast

for line in open("/app/backend/.env"):
    if line.startswith("MONGO_URL="):
        os.environ["MONGO_URL"] = line.split("=", 1)[1].strip().strip('"')
    elif line.startswith("DB_NAME="):
        os.environ["DB_NAME"] = line.split("=", 1)[1].strip().strip('"')

from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
UID = "user_test_employee01"

cmd = sys.argv[1]
if cmd == "check":
    u = db.users.find_one({"user_id": UID}) or {}
    print(json.dumps({
        "perms": u.get("allowed_permissions"),
        "curs": u.get("allowed_currencies"),
        "applied_templates": u.get("applied_templates"),
    }, default=str, indent=2))
elif cmd == "reset_all":
    db.users.update_one(
        {"user_id": UID},
        {"$set": {"allowed_permissions": ["support"], "allowed_currencies": ["USD"]},
         "$unset": {"applied_templates": ""}},
    )
    print("ok")
elif cmd == "set_curs":
    curs = ast.literal_eval(sys.argv[2])
    db.users.update_one({"user_id": UID}, {"$set": {"allowed_currencies": curs}})
    print("ok")
elif cmd == "restore":
    db.users.update_one(
        {"user_id": UID},
        {"$set": {"allowed_permissions": None, "allowed_currencies": []},
         "$unset": {"applied_templates": ""}},
    )
    print("ok")
