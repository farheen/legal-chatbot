import os
import zipfile
import json

# Directories
RAW_DATA_DIR = "../data/raw/"
PROCESSED_DATA_DIR = "../data/processed/"
os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)

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

def parse_json(data_dir):
    """
    Parse JSON files and extract meaningful fields for processing.
    """
    cases = []
    for root, dirs, files in os.walk(data_dir):
        for file in files:
            if file.endswith(".json"):
                with open(os.path.join(root, file), 'r') as f:
                    data = json.load(f)
                    case_text = data.get("text", "")
                    case_title = data.get("title", "Unknown Case")
                    cases.append({"title": case_title, "text": case_text})
    return cases

if __name__ == "__main__":
    print("Extracting raw data...")
    extract_files(RAW_DATA_DIR, PROCESSED_DATA_DIR)
    print("Parsing JSON files...")
    cases = parse_json(PROCESSED_DATA_DIR)
    print(f"Parsed {len(cases)} cases.")
