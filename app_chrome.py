from flask import Flask, request, url_for, session, redirect
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from pathlib import Path

import os
import sys
import shutil
import time
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


# ============================================================
# APPLICATION
# ============================================================

app = Flask(__name__)

app.secret_key = "your_secret"

app.config["SESSION_COOKIE_NAME"] = "Wong_Cookie"

TOKEN_INFO = "token_info"


# ============================================================
# Y2MATE CONFIGURATION
# ============================================================

Y2MATE_URL = "https://y2mate.gs/"

# Seconds to wait for Y2Mate conversion/download.
DOWNLOAD_TIMEOUT = 300

# Seconds to wait between checking the download folder.
DOWNLOAD_CHECK_INTERVAL = 2


# ============================================================
# GOOGLE OAUTH
# ============================================================

@app.route("/")
def login():

    sp_oauth = create_youtube_oauth()

    auth_url, state = sp_oauth.authorization_url(
        prompt="consent"
    )

    session["oauth_state"] = state
    session["code_verifier"] = sp_oauth.code_verifier

    return redirect(auth_url)


@app.route("/redirect")
def redirect_page():

    code = request.args.get("code")

    if not code:
        return (
            "Authorization failed: no code received.",
            400
        )

    sp_oauth = Flow.from_client_secrets_file(

        os.path.abspath(
            "client_secrets.json"
        ),

        scopes=[
            "https://www.googleapis.com/auth/youtube.readonly"
        ],

        state=session.get(
            "oauth_state"
        ),

        redirect_uri=url_for(
            "redirect_page",
            _external=True
        )
    )

    sp_oauth.code_verifier = session.get(
        "code_verifier"
    )

    sp_oauth.fetch_token(
        code=code
    )

    credentials = sp_oauth.credentials

    session[TOKEN_INFO] = credentials_to_dict(
        credentials
    )

    session.pop(
        "oauth_state",
        None
    )

    session.pop(
        "code_verifier",
        None
    )

    return redirect(
        url_for(
            "get_tracks",
            _external=True
        )
    )


def create_youtube_oauth():

    return Flow.from_client_secrets_file(

        os.path.abspath(
            "client_secrets.json"
        ),

        scopes=[
            "https://www.googleapis.com/auth/youtube.readonly"
        ],

        redirect_uri=url_for(
            "redirect_page",
            _external=True
        )
    )


# ============================================================
# CREDENTIALS
# ============================================================

def credentials_to_dict(creds):

    return {

        "token": creds.token,

        "refresh_token": creds.refresh_token,

        "token_uri": creds.token_uri,

        "client_id": creds.client_id,

        "client_secret": creds.client_secret,

        "scopes": creds.scopes
    }


def dict_to_credentials(data):

    return Credentials(

        token=data["token"],

        refresh_token=data.get(
            "refresh_token"
        ),

        token_uri=data["token_uri"],

        client_id=data["client_id"],

        client_secret=data["client_secret"],

        scopes=data["scopes"]
    )


def get_token():

    token_info = session.get(
        TOKEN_INFO
    )

    if not token_info:

        raise Exception(
            "No token found in session."
        )

    credentials = dict_to_credentials(
        token_info
    )

    if (
        credentials.expired
        and credentials.refresh_token
    ):

        credentials.refresh(
            Request()
        )

        session[TOKEN_INFO] = credentials_to_dict(
            credentials
        )

    return session[TOKEN_INFO]


# ============================================================
# SELENIUM DRIVER
# ============================================================

def create_browser(download_folder):

    """
    Create a Chrome browser configured to automatically
    download MP3 files into download_folder.
    """

    chrome_options = Options()

    # --------------------------------------------------------
    # Download configuration
    # --------------------------------------------------------

    preferences = {

        "download.default_directory": str(
            download_folder.resolve()
        ),

        "download.prompt_for_download": False,

        "download.directory_upgrade": True,

        "safebrowsing.enabled": True
    }

    chrome_options.add_experimental_option(
        "prefs",
        preferences
    )

    # --------------------------------------------------------
    # Browser behaviour
    # --------------------------------------------------------

    chrome_options.add_argument(
        "--start-maximized"
    )

    # --------------------------------------------------------
    # Uncomment this if you want Chrome invisible.
    #
    # For debugging, leave it commented.
    # --------------------------------------------------------

    # chrome_options.add_argument("--headless=new")

    # --------------------------------------------------------
    # Create browser
    # --------------------------------------------------------

    driver = webdriver.Chrome(
        options=chrome_options
    )

    return driver


# ============================================================
# DOWNLOAD CHECKING
# ============================================================

def get_downloaded_files(download_folder):

    """
    Return completed downloaded files.

    Chrome creates .crdownload files while a download
    is still in progress, so those are ignored.
    """

    files = set()

    for path in download_folder.iterdir():

        if not path.is_file():
            continue

        if path.name.endswith(
            ".crdownload"
        ):
            continue

        files.add(path)

    return files


def wait_for_download(
    download_folder,
    existing_files,
    timeout=DOWNLOAD_TIMEOUT
):

    """
    Wait until a new completed file appears.
    """

    start_time = time.time()

    while (
        time.time() - start_time
        < timeout
    ):

        current_files = get_downloaded_files(
            download_folder
        )

        new_files = (
            current_files
            - existing_files
        )

        if new_files:

            # Give Chrome a moment to finish
            # filesystem activity.
            time.sleep(1)

            return next(
                iter(new_files)
            )

        time.sleep(
            DOWNLOAD_CHECK_INTERVAL
        )

    raise TimeoutException(
        "Timed out waiting for Y2Mate download."
    )


# ============================================================
# Y2MATE DOWNLOAD
# ============================================================

def download_with_y2mate(
    driver,
    video_url,
    download_folder
):

    """
    Submit one YouTube URL to Y2Mate and wait for the
    resulting MP3 to download.

    Returns:
        Path to downloaded file
    """

    print()
    print(
        "Opening Y2Mate..."
    )

    # --------------------------------------------------------
    # Record files before starting
    # --------------------------------------------------------

    existing_files = get_downloaded_files(
        download_folder
    )

    # --------------------------------------------------------
    # Open Y2Mate
    # --------------------------------------------------------

    driver.get(
        Y2MATE_URL
    )

    wait = WebDriverWait(
        driver,
        30
    )

    # --------------------------------------------------------
    # Find video input
    # --------------------------------------------------------

    video_input = wait.until(

        EC.presence_of_element_located(
            (
                By.ID,
                "video"
            )
        )
    )

    # --------------------------------------------------------
    # Enter URL
    # --------------------------------------------------------

    video_input.clear()

    video_input.send_keys(
        video_url
    )

    # --------------------------------------------------------
    # Find MP3 button
    # --------------------------------------------------------

    # The page currently exposes MP3/MP4
    # buttons in the form.
    #
    # We look for a button whose visible
    # text is MP3.

    mp3_button = wait.until(

        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[normalize-space()='MP3']"
            )
        )
    )

    mp3_button.click()

    # --------------------------------------------------------
    # Click Convert
    # --------------------------------------------------------

    convert_button = wait.until(

        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[@type='submit'"
                " and normalize-space()='Convert']"
            )
        )
    )

    print(
        "Submitting video to Y2Mate..."
    )

    convert_button.click()

    # --------------------------------------------------------
    # Wait for conversion/download UI
    # --------------------------------------------------------

    print(
        "Waiting for conversion..."
    )

    # We don't assume a fixed HTML structure for
    # the resulting page.
    #
    # Instead, poll for a download link/button.

    download_button = None

    conversion_start = time.time()

    while (
        time.time() - conversion_start
        < DOWNLOAD_TIMEOUT
    ):

        try:

            # ------------------------------------------------
            # Look for a Download link/button
            # ------------------------------------------------

            elements = driver.find_elements(

                By.XPATH,

                "//a[contains("
                "translate(normalize-space(.),"
                "'DOWNLOAD','download'),"
                "'download')]"
                " | "
                "//button[contains("
                "translate(normalize-space(.),"
                "'DOWNLOAD','download'),"
                "'download')]"
            )

            for element in elements:

                if element.is_displayed():

                    try:

                        if element.is_enabled():

                            download_button = element

                            break

                    except Exception:
                        pass

            if download_button:

                break

        except Exception:
            pass

        time.sleep(2)

    # --------------------------------------------------------
    # Make sure download button appeared
    # --------------------------------------------------------

    if not download_button:

        raise Exception(
            "Y2Mate conversion did not produce "
            "a visible Download button within "
            f"{DOWNLOAD_TIMEOUT} seconds."
        )

    print(
        "Conversion complete."
    )

    # --------------------------------------------------------
    # Click Download
    # --------------------------------------------------------

    print(
        "Starting MP3 download..."
    )

    download_button.click()

    # --------------------------------------------------------
    # Wait for actual file
    # --------------------------------------------------------

    downloaded_file = wait_for_download(

        download_folder,

        existing_files
    )

    print()
    print(
        f"Downloaded: {downloaded_file}"
    )

    return downloaded_file


# ============================================================
# SANITIZE FILENAME
# ============================================================

def safe_filename(filename):

    """
    Remove characters that are problematic on Windows/macOS/Linux.
    """

    invalid_chars = '<>:"/\\|?*'

    for char in invalid_chars:

        filename = filename.replace(
            char,
            "_"
        )

    return filename.strip()


# ============================================================
# RENAME DOWNLOADED MP3
# ============================================================

def rename_downloaded_file(
    downloaded_file,
    song_title,
    save_folder
):

    """
    Rename the Y2Mate-generated filename to match
    the YouTube title.
    """

    clean_title = safe_filename(
        song_title
    )

    target = (
        save_folder
        / f"{clean_title}.mp3"
    )

    # --------------------------------------------------------
    # Avoid overwriting another file.
    # --------------------------------------------------------

    if target.exists():

        counter = 2

        while True:

            candidate = (

                save_folder
                / f"{clean_title} ({counter}).mp3"
            )

            if not candidate.exists():

                target = candidate

                break

            counter += 1

    downloaded_file.rename(
        target
    )

    return target


# ============================================================
# DOWNLOAD ALL SONGS
# ============================================================

def download_from_ids(
    songs,
    csv_path
):

    # --------------------------------------------------------
    # Create MP3 folder
    # --------------------------------------------------------

    save_path = (

        Path.home()
        / "Downloads"
        / "songs"
    )

    save_path.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Start Selenium
    # --------------------------------------------------------

    print()
    print(
        "=" * 60
    )

    print(
        "Y2MATE DOWNLOADER"
    )

    print(
        "=" * 60
    )

    print()

    print(
        f"Download folder: {save_path}"
    )

    print()

    driver = None

    successful = []

    failed = []

    try:

        driver = create_browser(
            save_path
        )

        # ====================================================
        # DOWNLOAD ONE VIDEO AT A TIME
        # ====================================================

        for index, song in enumerate(

            songs,

            start=1
        ):

            url = song["url"]

            title = song["title"]

            print()
            print(
                "=" * 60
            )

            print(
                f"[{index}/{len(songs)}] {title}"
            )

            print(
                url
            )

            print(
                "=" * 60
            )

            # ------------------------------------------------
            # Update CSV status
            # ------------------------------------------------

            song["status"] = "Downloading"

            song["error"] = ""

            try:

                # ------------------------------------------------
                # Send video to Y2Mate
                # ------------------------------------------------

                downloaded_file = download_with_y2mate(

                    driver,

                    url,

                    save_path
                )

                # ------------------------------------------------
                # Rename file
                # ------------------------------------------------

                final_file = rename_downloaded_file(

                    downloaded_file,

                    title,

                    save_path
                )

                # ------------------------------------------------
                # Success
                # ------------------------------------------------

                song["status"] = "Downloaded"

                song["error"] = ""

                successful.append(
                    song
                )

                print()

                print(
                    f"SUCCESS: {final_file}"
                )

            except Exception as e:

                error_message = str(e)

                song["status"] = "Failed"

                song["error"] = error_message

                failed.append(
                    song
                )

                print()

                print(
                    f"FAILED: {title}"
                )

                print(
                    f"Reason: {error_message}"
                )

            finally:

                # ------------------------------------------------
                # Save CSV after every video
                # ------------------------------------------------

                try:

                    pd.DataFrame(
                        songs
                    ).to_csv(

                        csv_path,

                        index=False
                    )

                except Exception as e:

                    print(
                        "Could not update CSV:"
                    )

                    print(
                        str(e)
                    )

    finally:

        # --------------------------------------------------------
        # Close browser
        # --------------------------------------------------------

        if driver:

            print()

            print(
                "Closing browser..."
            )

            driver.quit()

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print(
        "=" * 60
    )

    print(
        "DOWNLOAD SUMMARY"
    )

    print(
        "=" * 60
    )

    print()

    print(
        f"Total videos : {len(songs)}"
    )

    print(
        f"Downloaded   : {len(successful)}"
    )

    print(
        f"Failed       : {len(failed)}"
    )

    print()

    if failed:

        print(
            "FAILED DOWNLOADS"
        )

        print(
            "-" * 60
        )

        for song in failed:

            print()

            print(
                song["title"]
            )

            print(
                f"URL: {song['url']}"
            )

            print(
                f"Error: {song['error']}"
            )

    print()
    print(
        "=" * 60
    )

    print(
        "DOWNLOAD PROCESS FINISHED"
    )

    print(
        "=" * 60
    )

    return successful, failed


# ============================================================
# EXTRACT PLAYLIST ID FROM A LINK
# ============================================================

def extract_playlist_id(
    playlist_input
):

    """
    Accept either a full YouTube playlist link
    or a raw playlist ID.

    Examples:

        https://www.youtube.com/playlist?list=PL123
        https://youtube.com/playlist?list=PL123
        https://youtu.be/...?list=PL123
        PL123

    Returns the playlist ID, or None if not found.
    """

    import re

    # If the input is already a plain playlist ID.
    if re.fullmatch(
        r"[A-Za-z0-9_-]{10,}",
        playlist_input
    ):

        return playlist_input

    # Otherwise, look for list=... in the link.
    match = re.search(
        r"[?&]list=([A-Za-z0-9_-]+)",
        playlist_input
    )

    if match:

        return match.group(1)

    return None


# ============================================================
# CHOOSE WHICH VIDEOS TO DOWNLOAD
# ============================================================

def choose_songs(
    all_songs
):

    """
    Ask the user how they want to download:

        all   - download every video
        num   - download the first N videos
        after - download the videos that come after
                a given video number or video title

    Returns the list of songs to download.
    """

    while True:

        print(
            "How do you want to download?"
        )

        print(
            "  all   - download the entire playlist"
        )

        print(
            "  num   - download the first N videos"
        )

        print(
            "  after - download the videos after "
            "a video number or video title"
        )

        choice = input(
            "> "
        ).strip().lower()


        # ------------------------------------------------
        # Download everything
        # ------------------------------------------------

        if choice == "all":

            return list(
                all_songs
            )


        # ------------------------------------------------
        # Download first N videos
        # ------------------------------------------------

        if choice == "num":

            try:

                n = int(
                    input(
                        "How many videos to download? "
                    ).strip()
                )

            except ValueError:

                print()
                print(
                    "❌ Please enter a valid number."
                )
                print()

                continue

            if n <= 0:

                print()
                print(
                    "❌ Number must be at least 1."
                )
                print()

                continue

            return list(
                all_songs[:n]
            )


        # ------------------------------------------------
        # Download videos after a number or title
        # ------------------------------------------------

        if choice == "after":

            start = input(
                "Enter video number or title: "
            ).strip()

            if not start:

                print()
                print(
                    "❌ Please enter a video number or title."
                )
                print()

                continue

            # If the input is a number, use it directly.
            if start.isdigit():

                n = int(start)

                if n <= 0:

                    print()
                    print(
                        "❌ Number must be at least 1."
                    )
                    print()

                    continue

                if n >= len(all_songs):

                    print()
                    print(
                        "❌ That number is past the end "
                        "of the playlist."
                    )
                    print()

                    continue

                return list(
                    all_songs[n:]
                )

            # Otherwise, find the first video whose
            # title contains the given text.
            start_index = None

            for index, song in enumerate(
                all_songs
            ):

                if start.lower() in song["title"].lower():

                    start_index = index

                    break

            if start_index is None:

                print()
                print(
                    "❌ No video matched that title."
                )
                print()

                continue

            return list(
                all_songs[start_index + 1:]
            )


        # ------------------------------------------------
        # Invalid choice
        # ------------------------------------------------

        print()
        print(
            "❌ Invalid choice. "
            "Please enter 'all', 'num', or 'after'."
        )
        print()


# ============================================================
# GET PLAYLIST
# ============================================================

@app.route("/getTracks")
def get_tracks():

    # --------------------------------------------------------
    # Check authentication
    # --------------------------------------------------------

    try:

        token_info = get_token()

    except Exception as e:

        print(
            f"Error: {e}"
        )

        return redirect(
            "/"
        )

    credentials = dict_to_credentials(
        token_info
    )

    # --------------------------------------------------------
    # Connect to YouTube API
    # --------------------------------------------------------

    youtube = build(

        "youtube",

        "v3",

        credentials=credentials
    )

    # --------------------------------------------------------
    # Playlist ID
    # --------------------------------------------------------

    playlist_id = app.config.get(
        "PLAYLIST_ID"
    )

    if not playlist_id:

        return (
            "No playlist ID provided.",
            400
        )

    print()
    print(
        "=" * 60
    )

    print(
        "YouTube Playlist → Y2Mate → MP3"
    )

    print(
        "=" * 60
    )

    print()

    print(
        f"Playlist ID: {playlist_id}"
    )

    # --------------------------------------------------------
    # Get playlist videos
    # --------------------------------------------------------

    all_songs = []

    youtube_request = youtube.playlistItems().list(

        part="snippet",

        playlistId=playlist_id,

        maxResults=50
    )

    while youtube_request:

        try:

            response = youtube_request.execute()

        except Exception as e:

            print(
                "YouTube API request failed:"
            )

            print(
                str(e)
            )

            return (

                "Failed to read the YouTube playlist: "
                + str(e),

                500
            )

        items = response.get(
            "items",
            []
        )

        for item in items:

            snippet = item.get(
                "snippet",
                {}
            )

            resource_id = snippet.get(
                "resourceId",
                {}
            )

            video_id = resource_id.get(
                "videoId"
            )

            if not video_id:

                continue

            video_title = snippet.get(
                "title",
                "Unknown Title"
            )

            channel_title = snippet.get(

                "videoOwnerChannelTitle",

                "Unknown Channel"
            )

            video_url = (

                "https://www.youtube.com/watch?v="
                + video_id
            )

            all_songs.append({

                "title": video_title,

                "channel": channel_title,

                "video_id": video_id,

                "url": video_url,

                "status": "Pending",

                "error": ""
            })

        youtube_request = (

            youtube.playlistItems().list_next(

                youtube_request,

                response
            )
        )

    # --------------------------------------------------------
    # Empty playlist
    # --------------------------------------------------------

    if not all_songs:

        return (

            "No videos found in this playlist. "
            "Check that the playlist ID is correct "
            "and that your account has access to it."
        )

    print()

    print(
        f"Found {len(all_songs)} videos."
    )

    # --------------------------------------------------------
    # Print all video titles once
    # --------------------------------------------------------

    print()
    print(
        "Videos in playlist:"
    )

    print(
        "-" * 60
    )

    for index, song in enumerate(
        all_songs,
        start=1
    ):

        print(
            f"[{index}] {song['title']} "
            f"- {song['channel']}"
        )

        print(
            f"     {song['url']}"
        )

    print(
        "-" * 60
    )

    print()

    # --------------------------------------------------------
    # Let user choose what to download
    # --------------------------------------------------------

    selected_songs = choose_songs(
        all_songs
    )

    # --------------------------------------------------------
    # Download folder
    # --------------------------------------------------------

    downloads_folder = (

        Path.home()
        / "Downloads"
    )

    downloads_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # CSV
    # --------------------------------------------------------

    csv_path = (

        downloads_folder
        / "songs.csv"
    )

    # --------------------------------------------------------
    # Initial CSV
    # --------------------------------------------------------

    pd.DataFrame(
        all_songs
    ).to_csv(

        csv_path,

        index=False
    )

    print()

    print(
        f"CSV saved to: {csv_path}"
    )

    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

    successful, failed = download_from_ids(

        selected_songs,

        csv_path
    )

    # --------------------------------------------------------
    # Response
    # --------------------------------------------------------

    return (

        f"Download complete. "

        f"{len(successful)} downloaded, "

        f"{len(failed)} failed. "

        f"CSV saved to {csv_path}. "

        f"Check {downloads_folder / 'songs'}"
    )


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    print()
    print(
        "=" * 60
    )

    print(
        "YouTube Playlist → Y2Mate → MP3"
    )

    print(
        "=" * 60
    )

    print()

    print(
        f"Python: {sys.version}"
    )

    print()

    # --------------------------------------------------------
    # Ask playlist
    # --------------------------------------------------------

    playlist_input = input(

        "Enter YouTube Playlist Link or ID: "
    ).strip()

    if not playlist_input:

        print()

        print(
            "No playlist link or ID provided."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Extract playlist ID from the link
    # --------------------------------------------------------

    playlist_id = extract_playlist_id(
        playlist_input
    )

    if not playlist_id:

        print()

        print(
            "Could not find a playlist ID. "
            "Paste a YouTube playlist link "
            "or a playlist ID."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Store playlist
    # --------------------------------------------------------

    app.config[
        "PLAYLIST_ID"
    ] = playlist_id

    print()

    print(
        f"Using playlist: {playlist_id}"
    )

    print()

    print(
        "Starting Flask..."
    )

    print()

    app.run(

        debug=True,

        use_reloader=False
    )
