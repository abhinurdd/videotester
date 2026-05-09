import requests
import logging
import os
from pathlib import Path

logger = logging.getLogger("media_validator.r2_utils")

def download_from_url(url: str, download_path: str) -> bool:
    """
    Downloads a file from a given URL to the local download_path.
    Used for fetching videos from R2.
    """
    try:
        logger.info(f"Downloading file from URL: {url}")
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(download_path), exist_ok=True)
        
        with open(download_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        file_size = os.path.getsize(download_path)
        logger.info(f"Download complete: {download_path} ({file_size} bytes)")
        if file_size == 0:
            logger.error("Downloaded file is empty!")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to download from URL {url}: {e}")
        return False
