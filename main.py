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
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG_TEMPLATE, f, indent=4)
    print(f"A new template file '{CONFIG_FILE}' has been created. Please fill in your details.")


def human_size(size):
    for s in ["B", "kiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]:
        if abs(size) < 1024:
            break
        size = int(size / 1024)
    return f"{size}{s}"


def have_file(file, size, md5):
    """Determine whether the named file's contents have the given size and hash."""
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
    """Download a file from the given stream."""
    os.makedirs(os.path.dirname(file), exist_ok=True)
    with open(file, "bw") as dest:
        for chunk in stream.iter_content(chunk_size=None):
            dest.write(chunk)

class WaBackup:
    """Access WhatsApp backups stored in Google Drive."""

    def __init__(self, gmail, password, android_id):
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
        return self.get(
            path,
            None if page_token is None else {"pageToken": page_token},
        ).json()

    def list_path(self, path):
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
        return self.list_path("clients/wa/backups")

    def backup_files(self, backup):
        return self.list_path(f"{backup['name']}/files")

    def fetch(self, file):
        name = os.path.sep.join(file["name"].split("/")[3:])
        md5Hash = b64decode(file["md5Hash"], validate=True)
        if not have_file(name, int(file["sizeBytes"]), md5Hash):
            download_file(
                name,
                self.get(file["name"].replace("%", "%25").replace("+", "%2B"), {"alt": "media"}, stream=True)
            )

        return name, int(file["sizeBytes"]), md5Hash

    def fetch_all(self, backup, cksums):
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
    while True:
        response = input(f"\nDo you want {backup_name}? [y/n]: ").strip().lower()
        if response in ['y', 'n']:
            return response == 'y'
        print("Invalid input. Please enter 'y' or 'n'.")


def load_backups():
    wa_backup = WaBackup(**get_configs())
    backups = wa_backup.backups()
    return wa_backup, backups


def info():
    """Provide info about WhatsApp backups in Google Drive."""
    _, backups = load_backups()
    for backup in backups:
        if get_user_confirmation(backup["name"].split("/")[-1]):
            backup_info(backup)


def list_all():
    """List info about WhatsApp Files in Google Drive."""
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
    """Download all WhatsApp backups."""
    wa_backup, backups = load_backups()
    with open("md5sum.txt", "w", encoding="utf-8", buffering=1) as cksums:
        for backup in backups:
            if get_user_confirmation(backup["name"].split("/")[-1]):
                print(f"Backup Size: {human_size(int(backup['sizeBytes']))} Upload Time: {backup['updateTime']}")
                wa_backup.fetch_all(backup, cksums)

def menu():
    """Display the menu and handle user choices."""
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
