# WhatsApp Google Drive Extractor

Allows WhatsApp users on Android to extract their backed-up WhatsApp data
from Google Drive.

## Prerequisites

1. [Docker](https://docs.docker.com/get-docker/)
2. Android device with WhatsApp installed and the Google Drive backup feature enabled.
3. The device's Android ID (if you want to reduce the risk of being logged out of Google).
Run `adb shell settings get secure android_id` or search Google Play for "device ID" apps.
4. Google account login credentials (username and password). If using 2-factor authentication, create and use an App password: https://myaccount.google.com/apppasswords

## Instructions

1. Clone the repository:
   ```bash
   git clone https://github.com/daferferso/whatsapp-gdrive-extractor.git
   ```
2. Add your Gmail, password, and Android ID to the settings.json file before running the container.
3. Build the Docker image:
   ```bash
   cd whatsapp-gdrive-extractor/
   docker build . -t whatsapp-gdrive-extractor
   ```
4. Run the Docker container:

   **macOS / Linux:**
   ```bash
   # Replace <YOUR_USER> with your macOS username (e.g., andercmd)
   docker run -v $(pwd):/app -v ~/Downloads:/Users/<YOUR_USER>/Downloads -it whatsapp-gdrive-extractor
   ```

   **Windows (PowerShell):**
   ```powershell
   # Replace <YOUR_USER> with your Windows username
   docker run -v ${PWD}:/app -v $HOME\Downloads:/Users/<YOUR_USER>/Downloads -it whatsapp-gdrive-extractor
   ```

   > [!IMPORTANT]
   > Ensure the `download_path` in `settings.json` matches the internal container path (e.g., `/Users/<YOUR_USER>/Downloads/WhatsApp Backups`).

If downloading is interrupted, the files that were received successfully
won't be re-downloaded when running the tool one more time. After
downloading, you may verify the integrity of the downloaded files using
`md5sum --check md5sum.txt` on Linux or [md5summer](http://md5summer.org/) on Windows.

### Alternative authentication method

Instead of email and password, you can use an OAuth token to auth with Google. To obtain the value of the token, follow the instructions [here](https://github.com/rukins/gpsoauth-java/blob/b74ebca999d0f5bd38a2eafe3c0d50be552f6385/README.md#receiving-an-authentication-token). The token value should be in the format `oauth2_4/XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`. Put this into the `settings.json` file, and re-build and re-run the docker container. Note that this token expires quickly, and can be used only once. If this happend, you can just obtain a fresh token, replace the value in `settings.json` and re-build the docker container.

## Troubleshooting

1. ~~If you have `Error:Need Browser`, go to this url to solve the issue: https://accounts.google.com/b/0/DisplayUnlockCaptcha~~ Link no longer works 2025-12-11
2. If you experience issues authenticating (BadAuthentication errors) with Google using you email and password, you can try using the oauth token cookie instead of the password. See [Alternative authentication method](#alternative-authentication-method)

## Credits
-------

Author: TripCode

Contributors: DrDeath1122 from XDA for the multi-threading backbone part, [YuriCosta](https://github.com/YuriCosta) for reverse engineering the new restore system, and [macagua](https://github.com/macagua) for the [solution](https://github.com/YuriCosta/WhatsApp-GD-Extractor-Multithread/issues/54#issuecomment-2325571305) to the SSL problem.
Special thanks to [YuriCosta](https://github.com/YuriCosta), as I forked and improved his repository, adapting it to work with Docker along with [macagua](https://github.com/macagua)'s solution.