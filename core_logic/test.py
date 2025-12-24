import os
DB_PATH="./knowledge_base"

if os.path.exists(DB_PATH):
        print("Knowledge base found.")
else:
        print("Knowledge base not found. Please build the knowledge base first by running the rag.py.")