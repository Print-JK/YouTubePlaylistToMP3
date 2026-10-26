from flask import Flask, request, url_for, session, redirect
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from pathlib import Path

import os
import sys
import time
import shutil
import threading

import pandas as pd

from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException
)


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

# Maximum time to wait for Y2Mate conversion.
DOWNLOAD_TIMEOUT = 300

# Time between page checks.
DOWNLOAD_CHECK_INTERVAL = 2

# ============================================================
# THREADING
# ============================================================

# Number of Firefox workers running at the same time.
#
# Start with 2 or 3.
#
# Every worker has its own Firefox browser.
#
MAX_WORKERS = 3

# Number of attempts for a failed download.
#
# Example:
#
# 1 = no retry
# 2 = try once more
# 3 = try twice more
#
MAX_RETRIES = 2


# ============================================================
# LOCKS
# ============================================================

# Protects CSV operations and shared song status.
csv_lock = threading.Lock()

# Protects console output.
print_lock = threading.Lock()

# Protects final filename selection.
file_lock = threading.Lock()


# ============================================================
# THREAD-SAFE PRINT
# ============================================================

def safe_print(*args, **kwargs):

    with print_lock:

        print(
            *args,
            **kwargs
        )


# ============================================================
# DOWNLOAD ERROR
# ============================================================

class DownloadError(Exception):

    """
    Exception containing:

        code
        message
    """

    def __init__(
        self,
        code,
        message
    ):

        self.code = code
        self.message = message

        super().__init__(
            message
        )


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

    session["code_verifier"] = (
        sp_oauth.code_verifier
    )

    return redirect(
        auth_url
    )


@app.route("/redirect")
def redirect_page():

    code = request.args.get(
        "code"
    )

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

    sp_oauth.code_verifier = (
        session.get(
            "code_verifier"
        )
    )

    sp_oauth.fetch_token(
        code=code
    )

    credentials = sp_oauth.credentials

    session[TOKEN_INFO] = (
        credentials_to_dict(
            credentials
        )
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

def credentials_to_dict(
    creds
):

    return {

        "token": creds.token,

        "refresh_token": creds.refresh_token,

        "token_uri": creds.token_uri,

        "client_id": creds.client_id,

        "client_secret": creds.client_secret,

        "scopes": creds.scopes
    }


def dict_to_credentials(
    data
):

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

        session[TOKEN_INFO] = (
            credentials_to_dict(
                credentials
            )
        )

    return session[
        TOKEN_INFO
    ]


# ============================================================
# FIREFOX
# ============================================================

def create_browser(
    download_folder
):

    """
    Create one Firefox browser for one worker.

    Each worker gets its own download folder.
    """

    firefox_options = Options()

    download_path = str(
        download_folder.resolve()
    )

    # --------------------------------------------------------
    # Firefox download configuration.
    # --------------------------------------------------------

    firefox_options.set_preference(
        "browser.download.folderList",
        2
    )

    firefox_options.set_preference(
        "browser.download.dir",
        download_path
    )

    firefox_options.set_preference(
        "browser.download.useDownloadDir",
        True
    )

    firefox_options.set_preference(
        "browser.download.manager.showWhenStarting",
        False
    )

    firefox_options.set_preference(
        "browser.download.always_ask_before_handling_new_types",
        False
    )

    # --------------------------------------------------------
    # Automatically save audio/video.
    # --------------------------------------------------------

    firefox_options.set_preference(

        "browser.helperApps.neverAsk.saveToDisk",

        ",".join([

            "audio/mpeg",

            "audio/mp3",

            "audio/x-mpeg",

            "audio/x-mpeg-3",

            "audio/mpeg3",

            "application/octet-stream",

            "video/mp4",

            "application/mp4"
        ])
    )

    firefox_options.set_preference(
        "browser.download.manager.showAlertOnComplete",
        False
    )

    firefox_options.set_preference(
        "browser.download.manager.closeWhenDone",
        True
    )

    # --------------------------------------------------------
    # Window size.
    # --------------------------------------------------------

    firefox_options.add_argument(
        "--width=1400"
    )

    firefox_options.add_argument(
        "--height=900"
    )

    # --------------------------------------------------------
    # Uncomment if you want Firefox hidden.
    # --------------------------------------------------------

    # firefox_options.add_argument(
    #     "--headless"
    # )

    # --------------------------------------------------------
    # Start Firefox.
    # --------------------------------------------------------

    driver = webdriver.Firefox(
        options=firefox_options
    )

    return driver


# ============================================================
# DOWNLOAD FILE CHECKING
# ============================================================

def get_downloaded_files(
    download_folder
):

    """
    Return completed files.

    Firefox temporary files ending in .part
    are ignored.
    """

    files = set()

    if not download_folder.exists():

        return files

    for path in download_folder.iterdir():

        if not path.is_file():

            continue

        if path.name.endswith(
            ".part"
        ):

            continue

        if path.name.endswith(
            ".crdownload"
        ):

            continue

        files.add(
            path
        )

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

        current_files = (
            get_downloaded_files(
                download_folder
            )
        )

        new_files = (
            current_files
            - existing_files
        )

        if new_files:

            # Give Firefox a moment.
            time.sleep(
                1
            )

            current_files = (
                get_downloaded_files(
                    download_folder
                )
            )

            new_files = (
                current_files
                - existing_files
            )

            if new_files:

                return next(
                    iter(new_files)
                )

        time.sleep(
            DOWNLOAD_CHECK_INTERVAL
        )

    raise DownloadError(

        "DOWNLOAD_TIMEOUT",

        "The download file did not appear "
        f"within {timeout} seconds."
    )


# ============================================================
# PAGE ERROR DETECTION
# ============================================================

def inspect_page_for_errors(
    driver
):

    """
    Look for common Y2Mate errors.

    Returns:

        None

    or:

        (error_code, error_message)
    """

    try:

        body = driver.find_element(
            By.TAG_NAME,
            "body"
        )

        page_text = body.text

    except Exception:

        return None

    if not page_text:

        return None

    page_text_lower = (
        page_text.lower()
    )

    # ========================================================
    # SPECIFIC "CODE" DETECTION
    # ========================================================

    if "code" in page_text_lower:

        matching_lines = []

        for line in page_text.splitlines():

            if "code" in line.lower():

                clean_line = (
                    line.strip()
                )

                if clean_line:

                    matching_lines.append(
                        clean_line
                    )

        if matching_lines:

            message = (
                " | ".join(
                    matching_lines
                )
            )

        else:

            message = (
                "The word 'code' appeared on "
                "the Y2Mate page."
            )

        return (
            "CODE_ERROR",
            message
        )

    # ========================================================
    # INVALID VIDEO / URL
    # ========================================================

    error_keywords = {

        "invalid video":
            "INVALID_VIDEO",

        "invalid url":
            "INVALID_URL",

        "video unavailable":
            "VIDEO_UNAVAILABLE",

        "video not found":
            "VIDEO_NOT_FOUND",

        "unable to download":
            "DOWNLOAD_REJECTED",

        "cannot download":
            "DOWNLOAD_REJECTED",

        "could not download":
            "DOWNLOAD_REJECTED",

        "download failed":
            "DOWNLOAD_FAILED",

        "conversion failed":
            "CONVERSION_FAILED",

        "error occurred":
            "Y2MATE_ERROR",

        "something went wrong":
            "Y2MATE_ERROR"
    }

    for keyword, error_code in (
        error_keywords.items()
    ):

        if keyword in page_text_lower:

            return (
                error_code,
                f"Y2Mate page reported: {keyword}"
            )

    return None


# ============================================================
# Y2MATE DOWNLOAD
# ============================================================

def download_with_y2mate(
    driver,
    video_url,
    download_folder,
    worker_id
):

    """
    Download one YouTube URL.

    Raises DownloadError when something goes wrong.
    """

    safe_print(
        f"[Worker {worker_id}] Opening Y2Mate..."
    )

    # --------------------------------------------------------
    # Record files before download.
    # --------------------------------------------------------

    existing_files = (
        get_downloaded_files(
            download_folder
        )
    )

    # --------------------------------------------------------
    # Open Y2Mate.
    # --------------------------------------------------------

    try:

        driver.get(
            Y2MATE_URL
        )

    except Exception as e:

        raise DownloadError(
            "BROWSER_ERROR",
            f"Could not open Y2Mate: {e}"
        )

    wait = WebDriverWait(
        driver,
        30
    )

    # --------------------------------------------------------
    # Check page before doing anything.
    # --------------------------------------------------------

    page_error = (
        inspect_page_for_errors(
            driver
        )
    )

    if page_error:

        raise DownloadError(
            page_error[0],
            page_error[1]
        )

    # --------------------------------------------------------
    # Video input.
    # --------------------------------------------------------

    try:

        video_input = wait.until(

            EC.presence_of_element_located(
                (
                    By.ID,
                    "video"
                )
            )
        )

    except TimeoutException:

        raise DownloadError(

            "INPUT_NOT_FOUND",

            "Could not find the Y2Mate video input."
        )

    # --------------------------------------------------------
    # Enter URL.
    # --------------------------------------------------------

    try:

        video_input.clear()

        video_input.send_keys(
            video_url
        )

    except Exception as e:

        raise DownloadError(

            "INPUT_ERROR",

            f"Could not enter video URL: {e}"
        )

    # --------------------------------------------------------
    # Check URL.
    # --------------------------------------------------------

    if not video_url:

        raise DownloadError(

            "INVALID_URL",

            "The video URL is empty."
        )

    if (
        "youtube.com" not in video_url.lower()
        and "youtu.be" not in video_url.lower()
    ):

        raise DownloadError(

            "INVALID_URL",

            f"URL does not appear to be a YouTube URL: "
            f"{video_url}"
        )

    # --------------------------------------------------------
    # MP3 button.
    # --------------------------------------------------------

    try:

        mp3_button = wait.until(

            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[normalize-space()='MP3']"
                )
            )
        )

    except TimeoutException:

        page_error = (
            inspect_page_for_errors(
                driver
            )
        )

        if page_error:

            raise DownloadError(
                page_error[0],
                page_error[1]
            )

        raise DownloadError(

            "MP3_BUTTON_NOT_FOUND",

            "Could not find the MP3 button."
        )

    try:

        mp3_button.click()

    except Exception as e:

        raise DownloadError(

            "MP3_BUTTON_ERROR",

            f"Could not click MP3 button: {e}"
        )

    # --------------------------------------------------------
    # Convert button.
    # --------------------------------------------------------

    try:

        convert_button = wait.until(

            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[@type='submit'"
                    " and normalize-space()='Convert']"
                )
            )
        )

    except TimeoutException:

        page_error = (
            inspect_page_for_errors(
                driver
            )
        )

        if page_error:

            raise DownloadError(
                page_error[0],
                page_error[1]
            )

        raise DownloadError(

            "CONVERT_BUTTON_NOT_FOUND",

            "Could not find the Convert button."
        )

    # --------------------------------------------------------
    # Convert.
    # --------------------------------------------------------

    safe_print(
        f"[Worker {worker_id}] Submitting..."
    )

    try:

        convert_button.click()

    except Exception as e:

        raise DownloadError(

            "CONVERT_BUTTON_ERROR",

            f"Could not click Convert button: {e}"
        )

    # --------------------------------------------------------
    # Wait for conversion.
    # --------------------------------------------------------

    safe_print(
        f"[Worker {worker_id}] Converting..."
    )

    download_button = None

    conversion_start = time.time()

    while (
        time.time() - conversion_start
        < DOWNLOAD_TIMEOUT
    ):

        # ----------------------------------------------------
        # Check for errors.
        # ----------------------------------------------------

        page_error = (
            inspect_page_for_errors(
                driver
            )
        )

        if page_error:

            raise DownloadError(
                page_error[0],
                page_error[1]
            )

        # ----------------------------------------------------
        # Look for Download button.
        # ----------------------------------------------------

        try:

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

                try:

                    if not element.is_displayed():

                        continue

                    if not element.is_enabled():

                        continue

                    download_button = element

                    break

                except Exception:

                    continue

            if download_button:

                break

        except Exception:

            pass

        time.sleep(
            DOWNLOAD_CHECK_INTERVAL
        )

    # --------------------------------------------------------
    # Conversion timeout.
    # --------------------------------------------------------

    if not download_button:

        # One final error inspection.
        page_error = (
            inspect_page_for_errors(
                driver
            )
        )

        if page_error:

            raise DownloadError(
                page_error[0],
                page_error[1]
            )

        raise DownloadError(

            "CONVERSION_TIMEOUT",

            "Y2Mate did not produce a visible "
            "Download button within "
            f"{DOWNLOAD_TIMEOUT} seconds."
        )

    safe_print(
        f"[Worker {worker_id}] "
        f"Conversion complete."
    )

    # --------------------------------------------------------
    # Click Download.
    # --------------------------------------------------------

    safe_print(
        f"[Worker {worker_id}] "
        f"Starting MP3 download..."
    )

    try:

        download_button.click()

    except Exception as e:

        raise DownloadError(

            "DOWNLOAD_BUTTON_ERROR",

            f"Could not click Download button: {e}"
        )

    # --------------------------------------------------------
    # Wait for file.
    # --------------------------------------------------------

    downloaded_file = wait_for_download(

        download_folder,

        existing_files
    )

    safe_print(
        f"[Worker {worker_id}] "
        f"Downloaded: {downloaded_file.name}"
    )

    return downloaded_file


# ============================================================
# SAFE FILENAME
# ============================================================

def safe_filename(
    filename
):

    invalid_chars = '<>:"/\\|?*'

    for char in invalid_chars:

        filename = filename.replace(
            char,
            "_"
        )

    filename = filename.strip()

    # Remove trailing dots.
    filename = filename.rstrip(
        "."
    )

    if not filename:

        filename = "Unknown Title"

    return filename


# ============================================================
# RENAME / MOVE FILE
# ============================================================

def rename_downloaded_file(
    downloaded_file,
    song_title,
    save_folder
):

    """
    Move downloaded file into final directory.

    File naming is protected by file_lock.
    """

    clean_title = safe_filename(
        song_title
    )

    with file_lock:

        target = (
            save_folder
            / f"{clean_title}.mp3"
        )

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

        try:

            shutil.move(

                str(downloaded_file),

                str(target)
            )

        except Exception as e:

            raise DownloadError(

                "FILE_ERROR",

                f"Could not move downloaded file: {e}"
            )

    return target


# ============================================================
# SAVE CSV
# ============================================================

def save_csv(
    songs,
    csv_path
):

    """
    Save CSV safely.

    The lock also prevents two threads from changing
    status at the same time.
    """

    with csv_lock:

        try:

            pd.DataFrame(
                songs
            ).to_csv(

                csv_path,

                index=False
            )

        except Exception as e:

            safe_print(
                f"Could not update CSV: {e}"
            )


# ============================================================
# UPDATE SONG STATUS
# ============================================================

def update_song(
    song,
    songs,
    csv_path,
    status,
    code,
    error=""
):

    """
    Update song status and immediately save CSV.
    """

    with csv_lock:

        song["status"] = status

        song["code"] = code

        song["error"] = error

        try:

            pd.DataFrame(
                songs
            ).to_csv(

                csv_path,

                index=False
            )

        except Exception as e:

            safe_print(
                f"Could not update CSV: {e}"
            )


# ============================================================
# DOWNLOAD ONE SONG
# ============================================================

def process_song(
    driver,
    song,
    songs,
    index,
    total,
    save_path,
    temp_folder,
    csv_path,
    worker_id
):

    """
    Process one song using an existing Firefox instance.
    """

    title = song["title"]

    url = song["url"]

    # --------------------------------------------------------
    # Mark as downloading.
    # --------------------------------------------------------

    update_song(

        song,

        songs,

        csv_path,

        "Downloading",

        "DOWNLOADING",

        ""
    )

    safe_print()
    safe_print(
        "=" * 60
    )

    safe_print(
        f"[Worker {worker_id}] "
        f"[{index}/{total}] {title}"
    )

    safe_print(
        f"[Worker {worker_id}] URL: {url}"
    )

    safe_print(
        "=" * 60
    )

    last_code = "UNKNOWN_ERROR"

    last_error = "Unknown error."

    # ========================================================
    # RETRY LOOP
    # ========================================================

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            # ------------------------------------------------
            # Clean temporary directory before retry.
            # ------------------------------------------------

            for old_file in (
                temp_folder.iterdir()
            ):

                try:

                    if old_file.is_file():

                        old_file.unlink()

                    elif old_file.is_dir():

                        shutil.rmtree(
                            old_file,
                            ignore_errors=True
                        )

                except Exception:

                    pass

            # ------------------------------------------------
            # Download.
            # ------------------------------------------------

            downloaded_file = (
                download_with_y2mate(

                    driver,

                    url,

                    temp_folder,

                    worker_id
                )
            )

            # ------------------------------------------------
            # Move to final folder.
            # ------------------------------------------------

            final_file = (
                rename_downloaded_file(

                    downloaded_file,

                    title,

                    save_path
                )
            )

            # ------------------------------------------------
            # Success.
            # ------------------------------------------------

            update_song(

                song,

                songs,

                csv_path,

                "Downloaded",

                "SUCCESS",

                ""
            )

            safe_print()
            safe_print(
                f"[Worker {worker_id}] "
                f"SUCCESS: {final_file}"
            )

            return {
                "success": True,
                "song": song,
                "code": "SUCCESS",
                "error": ""
            }

        except DownloadError as e:

            last_code = e.code

            last_error = e.message

            safe_print()
            safe_print(
                f"[Worker {worker_id}] "
                f"Attempt {attempt}/{MAX_RETRIES} failed."
            )

            safe_print(
                f"[Worker {worker_id}] "
                f"CODE: {e.code}"
            )

            safe_print(
                f"[Worker {worker_id}] "
                f"ERROR: {e.message}"
            )

            # ------------------------------------------------
            # Don't retry certain permanent errors.
            # ------------------------------------------------

            permanent_codes = {

                "INVALID_URL",

                "INVALID_VIDEO",

                "VIDEO_UNAVAILABLE",

                "VIDEO_NOT_FOUND",

                "CODE_ERROR",

                "INPUT_NOT_FOUND",

                "MP3_BUTTON_NOT_FOUND",

                "CONVERT_BUTTON_NOT_FOUND"
            }

            if e.code in permanent_codes:

                break

            # ------------------------------------------------
            # Retry if another attempt remains.
            # ------------------------------------------------

            if attempt < MAX_RETRIES:

                safe_print(
                    f"[Worker {worker_id}] "
                    f"Retrying in 3 seconds..."
                )

                time.sleep(
                    3
                )

        except WebDriverException as e:

            last_code = "BROWSER_ERROR"

            last_error = str(
                e
            )

            safe_print()
            safe_print(
                f"[Worker {worker_id}] "
                f"Firefox error: {e}"
            )

            if attempt < MAX_RETRIES:

                safe_print(
                    f"[Worker {worker_id}] "
                    f"Retrying in 3 seconds..."
                )

                time.sleep(
                    3
                )

        except Exception as e:

            last_error = str(
                e
            )

            if (
                "code"
                in last_error.lower()
            ):

                last_code = (
                    "CODE_ERROR"
                )

            else:

                last_code = (
                    "UNKNOWN_ERROR"
                )

            safe_print()
            safe_print(
                f"[Worker {worker_id}] "
                f"Unexpected error: {e}"
            )

            if attempt < MAX_RETRIES:

                safe_print(
                    f"[Worker {worker_id}] "
                    f"Retrying in 3 seconds..."
                )

                time.sleep(
                    3
                )

    # ========================================================
    # FINAL FAILURE
    # ========================================================

    update_song(

        song,

        songs,

        csv_path,

        "Failed",

        last_code,

        last_error
    )

    safe_print()
    safe_print(
        f"[Worker {worker_id}] "
        f"FAILED: {title}"
    )

    safe_print(
        f"[Worker {worker_id}] "
        f"CODE: {last_code}"
    )

    safe_print(
        f"[Worker {worker_id}] "
        f"ERROR: {last_error}"
    )

    return {
        "success": False,
        "song": song,
        "code": last_code,
        "error": last_error
    }


# ============================================================
# WORKER
# ============================================================

def worker(
    worker_id,
    songs,
    song_queue,
    save_path,
    csv_path
):

    """
    One persistent Firefox worker.

    The browser stays alive and processes multiple songs.
    """

    temp_folder = (

        save_path
        / "_temp"
        / f"worker_{worker_id}"
    )

    temp_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    driver = None

    successful = []

    failed = []

    try:

        safe_print()
        safe_print(
            f"[Worker {worker_id}] "
            f"Starting Firefox..."
        )

        driver = create_browser(
            temp_folder
        )

        safe_print(
            f"[Worker {worker_id}] "
            f"Firefox started."
        )

        # ----------------------------------------------------
        # Process assigned songs.
        # ----------------------------------------------------

        while True:

            try:

                index, song = (
                    song_queue.get_nowait()
                )

            except Exception:

                break

            try:

                result = process_song(

                    driver,

                    song,

                    songs,

                    index,

                    len(songs),

                    save_path,

                    temp_folder,

                    csv_path,

                    worker_id
                )

                if result["success"]:

                    successful.append(
                        result["song"]
                    )

                else:

                    failed.append(
                        result["song"]
                    )

            except Exception as e:

                # ------------------------------------------------
                # Last-resort protection.
                # ------------------------------------------------

                error_message = str(
                    e
                )

                if (
                    "code"
                    in error_message.lower()
                ):

                    error_code = (
                        "CODE_ERROR"
                    )

                else:

                    error_code = (
                        "UNKNOWN_ERROR"
                    )

                update_song(

                    song,

                    songs,

                    csv_path,

                    "Failed",

                    error_code,

                    error_message
                )

                failed.append(
                    song
                )

                safe_print(
                    f"[Worker {worker_id}] "
                    f"Unexpected worker error: "
                    f"{error_message}"
                )

            finally:

                # ------------------------------------------------
                # Clear browser state between songs.
                # ------------------------------------------------

                try:

                    driver.delete_all_cookies()

                except Exception:

                    pass

        return successful, failed

    finally:

        # --------------------------------------------------------
        # Close Firefox.
        # --------------------------------------------------------

        if driver:

            safe_print(
                f"[Worker {worker_id}] "
                f"Closing Firefox..."
            )

            try:

                driver.quit()

            except Exception:

                pass

        # --------------------------------------------------------
        # Remove worker temp directory.
        # --------------------------------------------------------

        try:

            if temp_folder.exists():

                shutil.rmtree(

                    temp_folder,

                    ignore_errors=True
                )

        except Exception:

            pass


# ============================================================
# DOWNLOAD ALL SONGS
# ============================================================

def download_from_ids(
    songs,
    csv_path
):

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
    # Temporary directory.
    # --------------------------------------------------------

    temp_root = (

        save_path
        / "_temp"
    )

    temp_root.mkdir(

        parents=True,

        exist_ok=True
    )

    # --------------------------------------------------------
    # Print startup information.
    # --------------------------------------------------------

    safe_print()
    safe_print(
        "=" * 60
    )

    safe_print(
        "Y2MATE FIREFOX THREADED DOWNLOADER"
    )

    safe_print(
        "=" * 60
    )

    safe_print()

    safe_print(
        f"Download folder : {save_path}"
    )

    safe_print(
        f"Firefox workers : {MAX_WORKERS}"
    )

    safe_print(
        f"Max retries     : {MAX_RETRIES}"
    )

    safe_print()

    # --------------------------------------------------------
    # Create initial CSV.
    # --------------------------------------------------------

    for song in songs:

        if "code" not in song:

            song["code"] = "PENDING"

        if "status" not in song:

            song["status"] = "Pending"

        if "error" not in song:

            song["error"] = ""

    save_csv(
        songs,
        csv_path
    )

    # ========================================================
    # CREATE SONG QUEUE
    # ========================================================

    import queue

    song_queue = queue.Queue()

    for index, song in enumerate(
        songs,
        start=1
    ):

        song_queue.put(
            (
                index,
                song
            )
        )

    # ========================================================
    # START WORKERS
    # ========================================================

    successful = []

    failed = []

    with ThreadPoolExecutor(

        max_workers=MAX_WORKERS

    ) as executor:

        futures = []

        for worker_id in range(
            1,
            MAX_WORKERS + 1
        ):

            future = executor.submit(

                worker,

                worker_id,

                songs,

                song_queue,

                save_path,

                csv_path
            )

            futures.append(
                future
            )

        # ----------------------------------------------------
        # Wait for workers.
        # ----------------------------------------------------

        for future in as_completed(
            futures
        ):

            try:

                worker_successful, worker_failed = (
                    future.result()
                )

                successful.extend(
                    worker_successful
                )

                failed.extend(
                    worker_failed
                )

            except Exception as e:

                safe_print(
                    "Unexpected worker error: "
                    f"{e}"
                )

    # --------------------------------------------------------
    # Final CSV.
    # --------------------------------------------------------

    save_csv(
        songs,
        csv_path
    )

    # --------------------------------------------------------
    # Remove temp directory.
    # --------------------------------------------------------

    try:

        if temp_root.exists():

            shutil.rmtree(

                temp_root,

                ignore_errors=True
            )

    except Exception:

        pass

    # ========================================================
    # SUMMARY
    # ========================================================

    safe_print()
    safe_print(
        "=" * 60
    )

    safe_print(
        "DOWNLOAD SUMMARY"
    )

    safe_print(
        "=" * 60
    )

    safe_print()

    safe_print(
        f"Total videos : {len(songs)}"
    )

    safe_print(
        f"Downloaded   : {len(successful)}"
    )

    safe_print(
        f"Failed       : {len(failed)}"
    )

    safe_print()

    # --------------------------------------------------------
    # Failure breakdown.
    # --------------------------------------------------------

    if failed:

        safe_print(
            "FAILURE CODES"
        )

        safe_print(
            "-" * 60
        )

        failure_counts = {}

        for song in failed:

            code = song.get(
                "code",
                "UNKNOWN_ERROR"
            )

            failure_counts[code] = (
                failure_counts.get(
                    code,
                    0
                ) + 1
            )

        for code, count in sorted(
            failure_counts.items()
        ):

            safe_print(
                f"{code}: {count}"
            )

        safe_print()

        # ----------------------------------------------------
        # Detailed failures.
        # ----------------------------------------------------

        safe_print(
            "FAILED DOWNLOADS"
        )

        safe_print(
            "-" * 60
        )

        for song in failed:

            safe_print()

            safe_print(
                f"Title : {song['title']}"
            )

            safe_print(
                f"URL   : {song['url']}"
            )

            safe_print(
                f"Code  : {song.get('code', '')}"
            )

            safe_print(
                f"Error : {song.get('error', '')}"
            )

    safe_print()
    safe_print(
        "=" * 60
    )

    safe_print(
        "DOWNLOAD PROCESS FINISHED"
    )

    safe_print(
        "=" * 60
    )

    return (
        successful,
        failed
    )


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

        safe_print(
            "How do you want to download?"
        )

        safe_print(
            "  all   - download the entire playlist"
        )

        safe_print(
            "  num   - download the first N videos"
        )

        safe_print(
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

                safe_print()
                safe_print(
                    "❌ Please enter a valid number."
                )
                safe_print()

                continue

            if n <= 0:

                safe_print()
                safe_print(
                    "❌ Number must be at least 1."
                )
                safe_print()

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

                safe_print()
                safe_print(
                    "❌ Please enter a video number or title."
                )
                safe_print()

                continue

            # If the input is a number, use it directly.
            if start.isdigit():

                n = int(start)

                if n <= 0:

                    safe_print()
                    safe_print(
                        "❌ Number must be at least 1."
                    )
                    safe_print()

                    continue

                if n >= len(all_songs):

                    safe_print()
                    safe_print(
                        "❌ That number is past the end "
                        "of the playlist."
                    )
                    safe_print()

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

                safe_print()
                safe_print(
                    "❌ No video matched that title."
                )
                safe_print()

                continue

            return list(
                all_songs[start_index + 1:]
            )


        # ------------------------------------------------
        # Invalid choice
        # ------------------------------------------------

        safe_print()
        safe_print(
            "❌ Invalid choice. "
            "Please enter 'all', 'num', or 'after'."
        )
        safe_print()


# ============================================================
# GET PLAYLIST
# ============================================================

@app.route("/getTracks")
def get_tracks():

    # --------------------------------------------------------
    # Check authentication.
    # --------------------------------------------------------

    try:

        token_info = get_token()

    except Exception as e:

        safe_print(
            f"Error: {e}"
        )

        return redirect(
            "/"
        )

    credentials = (
        dict_to_credentials(
            token_info
        )
    )

    # --------------------------------------------------------
    # Connect to YouTube API.
    # --------------------------------------------------------

    youtube = build(

        "youtube",

        "v3",

        credentials=credentials
    )

    # --------------------------------------------------------
    # Playlist ID.
    # --------------------------------------------------------

    playlist_id = app.config.get(
        "PLAYLIST_ID"
    )

    if not playlist_id:

        return (
            "No playlist ID provided.",
            400
        )

    safe_print()
    safe_print(
        "=" * 60
    )

    safe_print(
        "YouTube Playlist → Y2Mate → MP3"
    )

    safe_print(
        "=" * 60
    )

    safe_print()

    safe_print(
        f"Playlist ID: {playlist_id}"
    )

    # --------------------------------------------------------
    # Get playlist videos.
    # --------------------------------------------------------

    all_songs = []

    youtube_request = (
        youtube.playlistItems().list(

            part="snippet",

            playlistId=playlist_id,

            maxResults=50
        )
    )

    while youtube_request:

        try:

            response = (
                youtube_request.execute()
            )

        except Exception as e:

            safe_print(
                "YouTube API request failed:"
            )

            safe_print(
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

                "code": "PENDING",

                "error": ""
            })

        youtube_request = (

            youtube.playlistItems().list_next(

                youtube_request,

                response
            )
        )

    # --------------------------------------------------------
    # Empty playlist.
    # --------------------------------------------------------

    if not all_songs:

        return (

            "No videos found in this playlist. "
            "Check that the playlist ID is correct "
            "and that your account has access to it."
        )

    safe_print()

    safe_print(
        f"Found {len(all_songs)} videos."
    )

    # --------------------------------------------------------
    # Print all video titles once
    # --------------------------------------------------------

    safe_print()
    safe_print(
        "Videos in playlist:"
    )

    safe_print(
        "-" * 60
    )

    for index, song in enumerate(
        all_songs,
        start=1
    ):

        safe_print(
            f"[{index}] {song['title']} "
            f"- {song['channel']}"
        )

        safe_print(
            f"     {song['url']}"
        )

    safe_print(
        "-" * 60
    )

    safe_print()

    # --------------------------------------------------------
    # Let user choose what to download
    # --------------------------------------------------------

    selected_songs = choose_songs(
        all_songs
    )

    # --------------------------------------------------------
    # Downloads directory.
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
    # CSV.
    # --------------------------------------------------------

    csv_path = (

        downloads_folder
        / "songs.csv"
    )

    # --------------------------------------------------------
    # Initial CSV.
    # --------------------------------------------------------

    save_csv(

        all_songs,

        csv_path
    )

    safe_print()

    safe_print(
        f"CSV saved to: {csv_path}"
    )

    # --------------------------------------------------------
    # Download.
    # --------------------------------------------------------

    successful, failed = (
        download_from_ids(

            selected_songs,

            csv_path
        )
    )

    # --------------------------------------------------------
    # Response.
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

    safe_print()
    safe_print(
        "=" * 60
    )

    safe_print(
        "YouTube Playlist → Y2Mate → MP3"
    )

    safe_print(
        "=" * 60
    )

    safe_print()

    safe_print(
        f"Python: {sys.version}"
    )

    safe_print()

    # --------------------------------------------------------
    # Ask playlist.
    # --------------------------------------------------------

    playlist_input = input(

        "Enter YouTube Playlist Link or ID: "
    ).strip()

    if not playlist_input:

        safe_print()

        safe_print(
            "No playlist link or ID provided."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Extract playlist ID from the link.
    # --------------------------------------------------------

    playlist_id = extract_playlist_id(
        playlist_input
    )

    if not playlist_id:

        safe_print()

        safe_print(
            "Could not find a playlist ID. "
            "Paste a YouTube playlist link "
            "or a playlist ID."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Store playlist.
    # --------------------------------------------------------

    app.config[
        "PLAYLIST_ID"
    ] = playlist_id

    safe_print()

    safe_print(
        f"Using playlist: {playlist_id}"
    )

    safe_print()

    safe_print(
        f"Firefox workers: {MAX_WORKERS}"
    )

    safe_print(
        f"Max retries: {MAX_RETRIES}"
    )

    safe_print()

    safe_print(
        "Starting Flask..."
    )

    safe_print()

    app.run(

        debug=True,

        use_reloader=False
    )
