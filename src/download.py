import os
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# Base URL of the site
BASE_URL = "https://static.case.law/"

# Directory for saving raw zip files
RAW_DATA_DIR = "../data/raw/"
os.makedirs(RAW_DATA_DIR, exist_ok=True)

def get_links_from_page(url):
    """
    Get all links from a given page, handling both absolute and relative URLs.
    """
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch {url}")
    
    soup = BeautifulSoup(response.content, 'html.parser')
    links = []

    for link in soup.find_all('a', href=True):
        href = link['href']
        # If the href is a full URL, use it as-is
        if href.startswith('http'):
            links.append(href)
        # If the href is relative, concatenate with base URL
        else:
            links.append(url.rstrip('/') + '/' + href)
    
    return links

def download_zip_files(base_url, raw_data_dir):
    """
    Navigate folders and download all .zip files.
    """
    # Get folder links from the base URL
    folder_links = get_links_from_page(base_url)
    
    for folder in tqdm(folder_links, desc="Processing folders"):
        if folder.endswith('/'):  # It's a folder link
            folder_url = folder  # Folder URL is already correct
            file_links = get_links_from_page(folder_url)
            
            for file in file_links:
                if file.endswith('.zip'):  # It's a zip file
                    file_url = file  # File URL is already correct
                    file_name = file.split('/')[-1]
                    file_path = os.path.join(raw_data_dir, file_name)
                    
                    # Skip if file already exists
                    if os.path.exists(file_path):
                        print(f"{file_name} already exists. Skipping...")
                        continue
                    
                    # Download the zip file
                    print(f"Downloading {file_name}...")
                    response = requests.get(file_url, stream=True)
                    with open(file_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=1024):
                            if chunk:
                                f.write(chunk)
                    print(f"{file_name} downloaded successfully.")

if __name__ == "__main__":
    print("Starting download of zip files...")
    download_zip_files(BASE_URL, RAW_DATA_DIR)
    print("Download complete.")
