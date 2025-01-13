from transformers import AutoTokenizer
import json

# Path to the parsed cases JSON file
PARSED_CASES_PATH = "../legal-chatbot/data/processed/parsed_cases.json"

# Load parsed cases
with open(PARSED_CASES_PATH, 'r') as file:
    cases = json.load(file)

# Define model name
model_name = "bert-base-uncased"  # Replace with the model of your choice

# Load tokenizer
tokenizer = AutoTokenizer.from_pretrained(model_name)

# Tokenize the dataset
tokenized_cases = []
for case in cases:
    case_text = case.get("case_text", "")  # Safely get case_text
    tokenized_text = tokenizer.encode(case_text, truncation=True, padding="max_length", max_length=512)
    tokenized_cases.append({
        "input_ids": tokenized_text,
        "attention_mask": [1] * len(tokenized_text),
        "labels": tokenized_text[:128],  # Truncated for labels
    })

# Save the tokenized data for future use
TOKENIZED_DATA_PATH = "../legal-chatbot/data/processed/tokenized_cases.json"
with open(TOKENIZED_DATA_PATH, 'w') as tokenized_file:
    json.dump(tokenized_cases, tokenized_file)

print(f"Tokenized data saved to {TOKENIZED_DATA_PATH}")
