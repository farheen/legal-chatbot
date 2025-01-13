import torch
from torch.utils.data import DataLoader, Dataset
import json

# Load Tokenized Data
TOKENIZED_DATA_PATH = "../legal-chatbot/data/processed/tokenized_cases.json"
with open(TOKENIZED_DATA_PATH, "r") as file:
    tokenized_cases = json.load(file)

# Configuration
BATCH_SIZE = 8
TRAIN_SPLIT = 0.8

# Dataset Class
class LegalDataset(Dataset):
    def __init__(self, data):
        self.data = data

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        item = self.data[idx]
        return {
            "input_ids": torch.tensor(item["input_ids"], dtype=torch.long),
            "attention_mask": torch.tensor(item["attention_mask"], dtype=torch.long),
            "labels": torch.tensor(item["labels"], dtype=torch.long),
        }

# Split Data
train_size = int(TRAIN_SPLIT * len(tokenized_cases))
train_dataset = LegalDataset(tokenized_cases[:train_size])
val_dataset = LegalDataset(tokenized_cases[train_size:])

# DataLoaders
train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE)

# Print Dataset Sizes
print(f"Training set size: {len(train_dataset)}")
print(f"Validation set size: {len(val_dataset)}")

