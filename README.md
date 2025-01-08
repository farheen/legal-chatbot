# Legal Document Retrieval and Summarization System

This project builds a system for retrieving and summarizing legal case documents using a Large Language Model (LLM). The primary goal is to assist lawyers by providing relevant case law and concise summaries for legal queries.

---

## Features

- **Data Retrieval**: Download and preprocess legal documents from the Caselaw Access Project.
- **Search Index**: Efficiently retrieve documents using FAISS (vector-based search).
- **Summarization**: Summarize retrieved cases using LLMs like BERT or GPT.
- **Interactive Chatbot**: Query the system via a user-friendly interface.

---

## Project Structure

legal-chatbot/
│
├── data/
│   ├── raw/               # Raw downloaded data (zip files)
│   ├── processed/         # Preprocessed data (JSON/cleaned text)
│
├── src/
│   ├── download.py        # Script to download data
│   ├── preprocess.py      # Script to preprocess data
│   ├── index.py           # Script to create FAISS index
│   ├── query.py           # Script to retrieve results
│   ├── summarizer.py      # Script to summarize cases
│
├── notebooks/
│   ├── exploration.ipynb  # Jupyter notebook for experimentation
│
├── models/
│   ├── bert_model/        # Directory for model weights (if needed)
│
├── app/
│   ├── app.py             # Flask/Streamlit app for chatbot interface
│
├── README.md              # Project documentation
├── requirements.txt       # Python dependencies
├── .gitignore             # Ignored files and folders

