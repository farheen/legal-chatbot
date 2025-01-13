import json
import os

# Path to the parsed JSON file
PARSED_FILE = "../legal-chatbot/data/processed/parsed_cases.json"

# Load and inspect the data
if os.path.exists(PARSED_FILE):
    with open(PARSED_FILE, 'r') as f:
        data = json.load(f)
    print(f"Loaded {len(data)} cases from 'parsed_cases.json'")
    
    # Display the first case to inspect the structure
    print("Sample Case:", json.dumps(data[0], indent=2))
else:
    print("File 'parsed_cases.json' not found!")

