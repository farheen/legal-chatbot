from transformers import AutoModelForSequenceClassification, AutoTokenizer

# Define the model and tokenizer names
model_name = "bert-base-uncased"  # Replace with a legal-specific model if needed

# Number of labels for classification
num_labels = 2  # Example: Binary classification (change as per your task)

# Load the pretrained model for sequence classification
model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=num_labels)

# Load the tokenizer
tokenizer = AutoTokenizer.from_pretrained(model_name)

print("Model and tokenizer successfully loaded!")
