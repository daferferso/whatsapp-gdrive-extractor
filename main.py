#!/usr/bin/env python3

from base64 import b64decode
from multiprocessing.pool import ThreadPool
from tqdm import tqdm
import gpsoauth
import hashlib
import json
import os
import requests


CONFIG_FILE = "settings.json"
CONFIG_TEMPLATE = {
    "gmail": "alias@gmail.com",
    "password": "",
    "android_id": "0000000000000000",
}


def get_configs():
    """
    Load configuration settings from a JSON file.

    Returns:
        dict: A dictionary containing the configuration settings.

    Raises:
        KeyError: If any required key is missing from the configuration.
    """
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        for key in CONFIG_TEMPLATE:
            if key not in config:
                raise KeyError(f"Missing key '{key}' in config file.")
        return config
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"Error loading configuration: {e}")
        create_settings_file()
        return CONFIG_TEMPLATE


def create_settings_file():
    """
    Create a new settings JSON file with a template configuration.
    """
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG_TEMPLATE, f, indent=4)
    print(f"A new template file '{CONFIG_FILE}' has been created. Please fill in your details.")


def human_size(size):
    """
    Convert a size in bytes to a human-readable format.

    Args:
        size (int): The size in bytes.

    Returns:
        str: A string representation of the size in a human-readable format (e.g., "10 MiB").
    """
    for s in ["B", "kiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]:
        if abs(size) < 1024:
            break
        size = int(size / 1024)
    return f"{size}{s}"


def have_file(file, size, md5):
    """
    Determine whether the named file's contents have the given size and hash.

    Args:
        file (str): The path to the file.
        size (int): The expected size of the file.
        md5 (bytes): The expected MD5 hash of the file.

    Returns:
        bool: True if the file exists and matches the size and hash; otherwise, False.
    """
    if not os.path.exists(file) or size != os.path.getsize(file):
        return False

    digest = hashlib.md5()
    with open(file, "br") as input:
        while True:
            b = input.read(8 * 1024)
            if not b:
                break
            digest.update(b)

    return md5 == digest.digest()

def download_file(file, stream):
    """
    Download a file from the given stream.

    Args:
        file (str): The path to save the downloaded file.
        stream (requests.Response): The response stream from which to download the file.
    """
    os.makedirs(os.path.dirname(file), exist_ok=True)
    with open(file, "bw") as dest:
        for chunk in stream.iter_content(chunk_size=None):
            dest.write(chunk)

class WaBackup:
    """Class to access WhatsApp backups stored in Google Drive."""

    def __init__(self, gmail, password, android_id):
        """
        Initialize the WaBackup instance.

        Args:
            gmail (str): The user's Gmail address.
            password (str): The user's Gmail password.
            android_id (str): The user's Android ID.

        Raises:
            SystemExit: If login fails.
        """
        token = gpsoauth.perform_master_login(gmail, password, android_id)
        if "Token" not in token:
            quit(token)
        self.auth = gpsoauth.perform_oauth(
            gmail,
            token["Token"],
            android_id,
            "oauth2:https://www.googleapis.com/auth/drive.appdata",
            "com.whatsapp",
            "38a0f7d505fe18fec64fbf343ecaaaf310dbd799",
        )

    def get(self, path, params=None, **kwargs):
        """
        Send a GET request to the specified path.

        Args:
            path (str): The API endpoint path.
            params (dict): Optional parameters for the request.
            **kwargs: Additional keyword arguments for the request.

        Returns:
            requests.Response: The response object from the GET request.
        """
        try:
            response = requests.get(
                f"https://backup.googleapis.com/v1/{path}",
                headers={"Authorization": f"Bearer {self.auth['Auth']}"},
                params=params,
                **kwargs,
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as errh:
            print ("\n\nHttp Error:",errh)
        except requests.exceptions.ConnectionError as errc:
            print ("\n\nError Connecting:",errc)
        except requests.exceptions.Timeout as errt:
            print ("\n\nTimeout Error:",errt)
        except requests.exceptions.RequestException as err:
            print ("\n\nOOps: Something Else",err)
        return response

    def get_page(self, path, page_token=None):
        """
        Retrieve a page of results from the specified path.

        Args:
            path (str): The API endpoint path.
            page_token (str): Optional token for pagination.

        Returns:
            dict: The JSON response from the API.
        """
        return self.get(
            path,
            None if page_token is None else {"pageToken": page_token},
        ).json()

    def list_path(self, path):
        """
        List items in the specified path.

        Args:
            path (str): The path to list items from.

        Yields:
            dict: Each item in the path.
        """
        last_component = path.split("/")[-1]
        page_token = None
        while True:
            page = self.get_page(path, page_token)
            for item in page[last_component]:
                yield item
            if "nextPageToken" not in page:
                break
            page_token = page["nextPageToken"]

    def backups(self):
        """
        List all WhatsApp backups.

        Returns:
            generator: A generator yielding backup items.
        """
        return self.list_path("clients/wa/backups")

    def backup_files(self, backup):
        """
        List files in the specified backup.

        Args:
            backup (dict): A backup item.

        Returns:
            generator: A generator yielding file items.
        """
        return self.list_path(f"{backup['name']}/files")

    def fetch(self, file):
        """
        Fetch and download a specific file.

        Args:
            file (dict): The file item to fetch.

        Returns:
            tuple: A tuple containing the file name, size, and MD5 hash.
        """
        name = os.path.sep.join(file["name"].split("/")[3:])
        md5Hash = b64decode(file["md5Hash"], validate=True)
        if not have_file(name, int(file["sizeBytes"]), md5Hash):
            download_file(
                name,
                self.get(file["name"].replace("%", "%25").replace("+", "%2B"), {"alt": "media"}, stream=True)
            )

        return name, int(file["sizeBytes"]), md5Hash

    def fetch_all(self, backup, cksums):
        """
        Fetch and download all files in a backup.

        Args:
            backup (dict): The backup item.
            cksums (TextIOWrapper): The file to write checksums to.
        """
        num_files = 0
        total_size = 0
        files = list(self.backup_files(backup))

        with ThreadPool(10) as pool, tqdm(total=len(files), desc="Downloading files") as pbar:
            downloads = pool.imap_unordered(
                lambda file: self.fetch(file),
                files
            )
            for name, size, md5Hash in downloads:
                num_files += 1
                total_size += size
                pbar.update(1)
                cksums.write(f"{md5Hash.hex()} *{name}\n")

        print(f"\n{num_files} files ({human_size(total_size)})")


def backup_info(backup):
    """
    Display information about a specific backup.

    Args:
        backup (dict): The backup item.
    """
    metadata = json.loads(backup["metadata"])
    for size in ["backupSize", "chatdbSize", "mediaSize", "videoSize"]:
        metadata[size] = human_size(int(metadata[size]))
    
    print(f"Backup {backup['name'].split('/')[-1]} Size:({metadata['backupSize']}) Upload Time: {backup['updateTime']}")
    print(f"  WhatsApp version  : {metadata['versionOfAppWhenBackup']}")
    print(f"  Password protected: {metadata.get('passwordProtectedBackupEnabled', 'N/A')}")
    print(f"  Messages          : {metadata['numOfMessages']} ({metadata['chatdbSize']})")
    print(f"  Media files       : {metadata['numOfMediaFiles']} ({metadata['mediaSize']})")
    print(f"  Photos            : {metadata['numOfPhotos']}")
    print(f"  Videos            : included={metadata['includeVideosInBackup']} ({metadata['videoSize']})")


def get_user_confirmation(backup_name):
    """
    Prompt the user for confirmation to proceed with a specific backup.

    Args:
        backup_name (str): The name of the backup to confirm.

    Returns:
        bool: True if the user confirms ('y'), False otherwise ('n').
    """
    while True:
        response = input(f"\nDo you want {backup_name}? [y/n]: ").strip().lower()
        if response in ['y', 'n']:
            return response == 'y'
        print("Invalid input. Please enter 'y' or 'n'.")


def load_backups():
    """
    Load WhatsApp backups using user credentials from the configuration file.

    Returns:
        tuple: A tuple containing the WaBackup instance and a list of backups.
    """
    wa_backup = WaBackup(**get_configs())
    backups = wa_backup.backups()
    return wa_backup, backups


def info():
    """
    Provide information about WhatsApp backups stored in Google Drive.

    This function iterates through the available backups and displays
    detailed information about each, if the user confirms they want to see it.
    """
    _, backups = load_backups()
    for backup in backups:
        if get_user_confirmation(backup["name"].split("/")[-1]):
            backup_info(backup)


def list_all():
    """
    List all WhatsApp files in Google Drive.

    This function prompts the user to confirm each backup and then
    lists all the files associated with the confirmed backups, along with
    their sizes.
    """
    wa_backup, backups = load_backups()
    for backup in backups:
        if get_user_confirmation(backup["name"].split("/")[-1]):
            num_files = 0
            total_size = 0
            for file in wa_backup.backup_files(backup):
                try:
                    num_files += 1
                    total_size += int(file["sizeBytes"])
                    print(os.path.sep.join(file["name"].split("/")[3:]))
                except Exception as e:
                    print(f"\nError processing file: {e}")
            print(f"{num_files} files ({human_size(total_size)})")


def sync():
    """
    Download all WhatsApp backups.

    This function downloads each backup the user confirms and writes the
    MD5 checksums of the downloaded files to a text file named 'md5sum.txt'.
    """
    wa_backup, backups = load_backups()
    with open("md5sum.txt", "w", encoding="utf-8", buffering=1) as cksums:
        for backup in backups:
            if get_user_confirmation(backup["name"].split("/")[-1]):
                print(f"Backup Size: {human_size(int(backup['sizeBytes']))} Upload Time: {backup['updateTime']}")
                wa_backup.fetch_all(backup, cksums)

def menu():
    """
    Display a menu for the user to choose options for managing WhatsApp backups.

    This function continuously prompts the user for input and executes the
    corresponding function based on their choice.
    """
    options = {
        '1': info,
        '2': list_all,
        '3': sync,
        '4': exit,
    }

    while True:
        print("\nMenu:")
        print("1. Info - Provide info about your WhatsApp backups in Google Drive")
        print("2. List - Provide info about your WhatsApp Files in Google Drive")
        print("3. Sync - Download all WhatsApp backups")
        print("4. Exit")

        choice = input("Please enter your choice: ")
        if choice in options:
            options[choice]()
        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    menu()
