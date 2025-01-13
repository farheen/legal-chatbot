import os
import zipfile
import json

# Directories
RAW_DATA_DIR = "../legal-chatbot/data/raw/"
PROCESSED_DATA_DIR = "../legal-chatbot/data/processed/"
JSON_SUBDIR = os.path.join(PROCESSED_DATA_DIR, "json")  # Subdirectory for JSON files
os.makedirs(JSON_SUBDIR, exist_ok=True)

def extract_files(input_dir, output_dir):
    """
    Extract all `.zip` files from the input directory to the output directory.
    """
    for file_name in os.listdir(input_dir):
        if file_name.endswith(".zip"):
            file_path = os.path.join(input_dir, file_name)
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(output_dir)
            print(f"Extracted: {file_name}")
    print(f"All ZIP files extracted to {output_dir}.")

def parse_json(input_dir):
    """
    Parse JSON files from the input directory.
    """
    cases = []
    json_dir = os.path.join(input_dir, "json")  # Adjusted to include the 'json' subdirectory
    if not os.path.exists(json_dir):
        print(f"No JSON directory found at {json_dir}.")
        return cases

    for file_name in os.listdir(json_dir):
        if file_name.endswith('.json'):
            file_path = os.path.join(json_dir, file_name)
            with open(file_path, 'r') as f:
                data = json.load(f)
                # Handle different JSON structures
                if isinstance(data, list):  # List of cases
                    for item in data:
                        cases.append(extract_relevant_data(item))
                elif isinstance(data, dict):  # Single case or cases key
                    if "cases" in data:  # Check for cases key
                        for item in data["cases"]:
                            cases.append(extract_relevant_data(item))
                    else:  # Handle single case
                        cases.append(extract_relevant_data(data))
                else:
                    print(f"Unexpected JSON structure in {file_name}. Skipping.")
    return cases

def extract_relevant_data(data):
    """
    Extract relevant fields from a single case.
    """
    # Extract opinions text safely
    opinions = data.get("casebody", {}).get("opinions", [])
    case_text = opinions[0].get("text", "") if opinions and isinstance(opinions, list) else ""

    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "decision_date": data.get("decision_date"),
        "jurisdiction": data.get("jurisdiction", {}).get("name_long"),
        "court": data.get("court", {}).get("name"),
        "case_text": case_text,
    }

if __name__ == "__main__":
    print("Extracting raw data...")
    extract_files(RAW_DATA_DIR, PROCESSED_DATA_DIR)

    print("Parsing JSON files...")
    cases = parse_json(PROCESSED_DATA_DIR)

    print(f"Parsed {len(cases)} cases.")
    # Save parsed cases to a file
    output_file = os.path.join(PROCESSED_DATA_DIR, "parsed_cases.json")
    with open(output_file, 'w') as f:
        json.dump(cases, f, indent=4)
    print(f"Saved parsed cases to {output_file}.")
