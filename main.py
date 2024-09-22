#!/usr/bin/env python3

from base64 import b64decode
from multiprocessing.pool import ThreadPool
import click
import gpsoauth
import hashlib
import json
import os
import requests
import traceback


CONFIG_FILE = "settings.json"
CONFIG_TEMPLATE = {
    "gmail": "alias@gmail.com",
    "password": "",
    "android_id": "0000000000000000",
}


def human_size(size):
    for s in ["B", "kiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]:
        if abs(size) < 1024:
            break
        size = int(size / 1024)
    return "{}{}".format(size, s)


def have_file(file, size, md5):
    """
    Determine whether the named file's contents have the given size and hash.
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
    """
    os.makedirs(os.path.dirname(file), exist_ok=True)
    with open(file, "bw") as dest:
        for chunk in stream.iter_content(chunk_size=None):
            dest.write(chunk)

class WaBackup:
    """
    Provide access to WhatsApp backups stored in Google drive.
    """
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
                "https://backup.googleapis.com/v1/{}".format(path),
                headers={"Authorization": "Bearer {}".format(self.auth["Auth"])},
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
        return self.list_path("{}/files".format(backup["name"]))

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
        with ThreadPool(10) as pool:
            downloads = pool.imap_unordered(
                lambda file: self.fetch(file),
                self.backup_files(backup)
            )
            for name, size, md5Hash in downloads:
                num_files += 1
                total_size += size
                print(
                    "\rProgress: {:7.3f}% {:60}".format(
                        100 * total_size / int(backup["sizeBytes"]),
                        os.path.basename(name)[-60:]
                    ),
                    end="",
                    flush=True,
                )

                cksums.write("{md5Hash} *{name}\n".format(
                    name=name,
                    md5Hash=md5Hash.hex(),
                ))

        print("\n{} files ({})".format(num_files, human_size(total_size)))


def getConfigs():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        for key in CONFIG_TEMPLATE:
            if key not in config:
                raise KeyError(f"Missing key '{key}' in config file.")
        return config
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"Error loading configuration: {e}")
        createSettingsFile()
        return CONFIG_TEMPLATE


def createSettingsFile():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG_TEMPLATE, f, indent=4)
    print(
        f"A new template file '{CONFIG_FILE}' has been created. Please fill in your details. "
        f"Make sure to include all the necessary keys: {list(CONFIG_TEMPLATE.keys())}."
    )


def backup_info(backup):
    metadata = json.loads(backup["metadata"])
    for size in "backupSize", "chatdbSize", "mediaSize", "videoSize":
        metadata[size] = human_size(int(metadata[size]))
    print("Backup {} Size:({}) Upload Time:{}".format(backup["name"].split("/")[-1], metadata["backupSize"], backup["updateTime"]))
    print("  WhatsApp version  : {}".format(metadata["versionOfAppWhenBackup"]))
    try:
        print("  Password protected: {}".format(metadata["passwordProtectedBackupEnabled"]))
    except:
        pass
    print("  Messages          : {} ({})".format(metadata["numOfMessages"], metadata["chatdbSize"]))
    print("  Media files       : {} ({})".format(metadata["numOfMediaFiles"], metadata["mediaSize"]))
    print("  Photos            : {}".format(metadata["numOfPhotos"]))
    print("  Videos            : included={} ({})".format(metadata["includeVideosInBackup"], metadata["videoSize"]))


def load_backups():
    wa_backup = WaBackup(**getConfigs())
    backups = wa_backup.backups()
    return wa_backup, backups


@click.command()
def info():
    """
    Provide info about your WhatsApp backups in Google Drive
    """
    _, backups = load_backups()
    for backup in backups:
        answer = input(
            "\nDo you want {}? [y/n] : ".format(backup["name"].split("/")[-1])
        )
        if not answer or answer[0].lower() != "y":
            continue
        backup_info(backup)


@click.command('list')
def list_all():
    """
    Provide info about your WhatsApp Files in Google Drive
    """
    wa_backup, backups = load_backups()
    for backup in backups:
        answer = input(
            "\nDo you want {}? [y/n] : ".format(backup["name"].split("/")[-1])
        )
        if not answer or answer[0].lower() != "y":
            continue
        num_files = 0
        total_size = 0
        for file in wa_backup.backup_files(backup):
            try:
                num_files += 1
                total_size += int(file["sizeBytes"])
                print(os.path.sep.join(file["name"].split("/")[3:]))
            except:
                print(
                    "\n#####\n\nWarning: Unexpected error in file: {}\n\nDetail: {}\n\nException: {}\n\n#####\n".format(
                        os.path.sep.join(file["name"].split("/")[3:]),
                        json.dumps(file, indent=4, sort_keys=True),
                        traceback.format_exc(),
                    )
                )
                input("Press the <Enter> key to continue...")
                continue
        print("{} files ({})".format(num_files, human_size(total_size)))


@click.command()
def sync():
    """
    Download all WhatsApp backups
    """
    wa_backup, backups = load_backups()
    with open("md5sum.txt", "w", encoding="utf-8", buffering=1) as cksums:
        for backup in backups:
            try:
                answer = input(
                    "\nDo you want {}? [y/n] : ".format(backup["name"].split("/")[-1])
                )
                if not answer or answer[0].lower() != "y":
                    continue
                print(
                    "Backup Size:{} Upload Time: {}".format(
                        human_size(int(backup["sizeBytes"])), backup["updateTime"]
                    )
                )
                wa_backup.fetch_all(backup, cksums)
            except Exception as err:
                print(
                    "\n#####\n\nWarning: Unexpected error in backup: {} (Size:{} Upload Time: {})\n\nException: {}\n\n#####\n".format(
                        backup["name"].split("/")[-1],
                        human_size(int(backup["sizeBytes"])),
                        backup["updateTime"],
                        traceback.format_exc(),
                    )
                )
                input("Press the <Enter> key to continue...")


@click.group()
def cli():
    """
    WhatsApp GDrive Extractor.
    A tool that allows you to get information or download your WhatsApp backups from Google Drive.
    """
    pass


cli.add_command(info)
cli.add_command(list_all)
cli.add_command(sync)

if __name__ == "__main__":
    cli()
