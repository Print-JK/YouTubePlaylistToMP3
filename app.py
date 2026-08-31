from flask import Flask, request, url_for, session, redirect
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from pathlib import Path
import yt_dlp as youtube_dl
import os
import pandas as pd

# forked from Wong Wei Jun's YouTubeLikedVidsToMP3 Repo

app = Flask(__name__)

# Flask session configuration
app.secret_key = "your_secret"
app.config['SESSION_COOKIE_NAME'] = 'Wong_Cookie'

TOKEN_INFO = "token_info"


# ============================================================
# GOOGLE OAUTH
# ============================================================

@app.route('/')
def login():

    sp_oauth = create_youtube_oauth()

    auth_url, state = sp_oauth.authorization_url(
        prompt='consent'
    )

    # Save OAuth information so it survives the Google redirect
    session['oauth_state'] = state
    session['code_verifier'] = sp_oauth.code_verifier

    return redirect(auth_url)


@app.route('/redirect')
def redirect_page():

    code = request.args.get('code')

    if not code:
        return "Authorization failed: no code received.", 400

    sp_oauth = Flow.from_client_secrets_file(
        os.path.abspath("client_secrets.json"),
        scopes=[
            'https://www.googleapis.com/auth/youtube.readonly'
        ],
        state=session.get('oauth_state'),
        redirect_uri=url_for(
            'redirect_page',
            _external=True
        )
    )

    # Restore the PKCE verifier from the session
    sp_oauth.code_verifier = session.get('code_verifier')

    # Exchange authorization code for access token
    sp_oauth.fetch_token(code=code)

    credentials = sp_oauth.credentials

    session[TOKEN_INFO] = credentials_to_dict(
        credentials
    )

    # Clean up temporary OAuth information
    session.pop('oauth_state', None)
    session.pop('code_verifier', None)

    return redirect(
        url_for('get_tracks', _external=True)
    )


def create_youtube_oauth():

    return Flow.from_client_secrets_file(
        os.path.abspath("client_secrets.json"),
        scopes=[
            'https://www.googleapis.com/auth/youtube.readonly'
        ],
        redirect_uri=url_for(
            'redirect_page',
            _external=True
        )
    )


# ============================================================
# CREDENTIALS
# ============================================================

def credentials_to_dict(creds):

    return {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes
    }


def dict_to_credentials(data):

    return Credentials(
        token=data['token'],
        refresh_token=data.get('refresh_token'),
        token_uri=data['token_uri'],
        client_id=data['client_id'],
        client_secret=data['client_secret'],
        scopes=data['scopes']
    )


def get_token():

    token_info = session.get(TOKEN_INFO)

    if not token_info:
        raise Exception(
            "No token found in session."
        )

    credentials = dict_to_credentials(
        token_info
    )

    # Refresh expired credentials
    if credentials.expired and credentials.refresh_token:

        credentials.refresh(Request())

        session[TOKEN_INFO] = credentials_to_dict(
            credentials
        )

    return session[TOKEN_INFO]


# ============================================================
# GET PLAYLIST AND DOWNLOAD
# ============================================================

@app.route('/getTracks')
def get_tracks():

    # --------------------------------------------------------
    # Check authentication
    # --------------------------------------------------------

    try:

        token_info = get_token()

    except Exception as e:

        print(f"Error: {e}")

        return redirect("/")


    credentials = dict_to_credentials(
        token_info
    )


    # --------------------------------------------------------
    # Connect to YouTube API
    # --------------------------------------------------------

    youtube = build(
        'youtube',
        'v3',
        credentials=credentials
    )


    # --------------------------------------------------------
    # Get playlist ID
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
    print("=" * 60)
    print("YouTube Playlist → MP3")
    print("=" * 60)
    print()
    print(f"Playlist ID: {playlist_id}")
    print()


    all_songs = []


    # ========================================================
    # GET ALL VIDEOS FROM PLAYLIST
    # ========================================================

    youtube_request = youtube.playlistItems().list(
        part="snippet",
        playlistId=playlist_id,
        maxResults=50
    )


    while youtube_request:

        response = youtube_request.execute()

        items = response.get(
            "items",
            []
        )


        for item in items:

            snippet = item["snippet"]


            # ------------------------------------------------
            # Get actual video ID
            # ------------------------------------------------

            video_id = snippet[
                "resourceId"
            ][
                "videoId"
            ]


            # ------------------------------------------------
            # Get video information
            # ------------------------------------------------

            video_title = snippet[
                "title"
            ]

            channel_title = snippet.get(
                "videoOwnerChannelTitle",
                "Unknown Channel"
            )


            # ------------------------------------------------
            # Construct exact YouTube URL
            # ------------------------------------------------

            video_url = (
                f"https://www.youtube.com/watch?v={video_id}"
            )


            # ------------------------------------------------
            # Store information for CSV
            # ------------------------------------------------

            all_songs.append({

                "title": video_title,

                "channel": channel_title,

                "video_id": video_id,

                "url": video_url,

                "status": "Pending",

                "error": ""

            })


        # ----------------------------------------------------
        # Get next page
        # ----------------------------------------------------

        youtube_request = youtube.playlistItems().list_next(
            youtube_request,
            response
        )


    # ========================================================
    # CHECK IF PLAYLIST IS EMPTY
    # ========================================================

    if not all_songs:

        return (
            "No videos found in this playlist. "
            "Check that the playlist ID is correct "
            "and that your account has access to it."
        )


    print(
        f"Found {len(all_songs)} videos."
    )


    # ========================================================
    # DOWNLOAD FOLDER
    # ========================================================

    downloads_folder = (
        Path.home()
        / "Downloads"
    )


    downloads_folder.mkdir(
        parents=True,
        exist_ok=True
    )


    # ========================================================
    # CSV PATH
    # ========================================================

    csv_path = (
        downloads_folder
        / "songs.csv"
    )


    # ========================================================
    # SAVE INITIAL CSV
    # ========================================================

    df = pd.DataFrame(
        all_songs
    )


    df.to_csv(
        csv_path,
        index=False
    )


    print()
    print(
        f"CSV saved to: {csv_path}"
    )
    print()


    # ========================================================
    # PRINT WHAT WILL BE DOWNLOADED
    # ========================================================

    print("Videos to download:")
    print("-" * 60)


    for song in all_songs:

        print(
            f"{song['title']} "
            f"- {song['channel']}"
        )

        print(
            f"  {song['url']}"
        )

        print()


    print("-" * 60)
    print()


    # ========================================================
    # DOWNLOAD VIDEOS
    # ========================================================

    successful, failed = download_from_ids(
        all_songs,
        csv_path
    )


    # ========================================================
    # FINAL RESPONSE
    # ========================================================

    return (
        f"Download complete. "
        f"{len(successful)} downloaded, "
        f"{len(failed)} failed. "
        f"CSV saved to {csv_path}. "
        f"Check {downloads_folder / 'songs'}"
    )


# ============================================================
# YT-DLP DOWNLOAD
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
    # yt-dlp options
    # --------------------------------------------------------

    ydl_opts = {

        # Best available audio
        'format': 'bestaudio/best',

        # Convert audio to MP3
        'postprocessors': [

            {
                'key': 'FFmpegExtractAudio',

                'preferredcodec': 'mp3',

                'preferredquality': '192',
            }

        ],

        # Output filename
        'outtmpl': str(
            save_path
            / '%(title)s.%(ext)s'
        ),

    }


    successful = []

    failed = []


    print()
    print("=" * 60)
    print("🎶 DOWNLOADING MP3s")
    print("=" * 60)
    print()


    # ========================================================
    # DOWNLOAD ONE VIDEO AT A TIME
    # ========================================================

    with youtube_dl.YoutubeDL(
        ydl_opts
    ) as ydl:


        for index, song in enumerate(
            songs,
            start=1
        ):


            url = song["url"]

            title = song["title"]


            print()
            print("=" * 60)

            print(
                f"[{index}/{len(songs)}] "
                f"{title}"
            )

            print(url)

            print("=" * 60)


            # ------------------------------------------------
            # Mark as downloading
            # ------------------------------------------------

            song["status"] = "Downloading"

            song["error"] = ""


            try:

                # ------------------------------------------------
                # Download ONLY this video
                # ------------------------------------------------

                ydl.download(
                    [url]
                )


                # ------------------------------------------------
                # Mark successful
                # ------------------------------------------------

                song["status"] = "Downloaded"

                song["error"] = ""


                successful.append(
                    song
                )


                print()
                print(
                    f"✅ Downloaded: {title}"
                )


            except youtube_dl.utils.DownloadError as e:

                # ------------------------------------------------
                # yt-dlp download error
                # ------------------------------------------------

                error_message = str(e)


                song["status"] = "Failed"

                song["error"] = error_message


                failed.append(
                    song
                )


                print()
                print(
                    f"❌ Failed: {title}"
                )

                print(
                    f"   Reason: {error_message}"
                )


            except Exception as e:

                # ------------------------------------------------
                # Unexpected error
                # ------------------------------------------------

                error_message = str(e)


                song["status"] = "Failed"

                song["error"] = error_message


                failed.append(
                    song
                )


                print()
                print(
                    f"❌ Unexpected error: {title}"
                )

                print(
                    f"   Reason: {error_message}"
                )


            finally:

                # ------------------------------------------------
                # IMPORTANT:
                #
                # Save CSV after EVERY video.
                #
                # If the program crashes halfway through,
                # the CSV still contains everything processed
                # before the crash.
                # ------------------------------------------------

                pd.DataFrame(
                    songs
                ).to_csv(
                    csv_path,
                    index=False
                )


    # ========================================================
    # DOWNLOAD SUMMARY
    # ========================================================

    print()
    print("=" * 60)
    print("📊 DOWNLOAD SUMMARY")
    print("=" * 60)

    print(
        f"Total videos : {len(songs)}"
    )

    print(
        f"Downloaded   : {len(successful)}"
    )

    print(
        f"Failed       : {len(failed)}"
    )


    # ========================================================
    # PRINT FAILED DOWNLOADS
    # ========================================================

    if failed:

        print()
        print("❌ FAILED DOWNLOADS")
        print("-" * 60)


        for song in failed:

            print(
                song["title"]
            )

            print(
                f"  URL: {song['url']}"
            )

            print(
                f"  Error: {song['error']}"
            )

            print()


    print("=" * 60)

    print(
        "✅ DOWNLOAD PROCESS FINISHED"
    )

    print("=" * 60)
    print()


    return successful, failed


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("YouTube Playlist → MP3")
    print("=" * 60)
    print()


    # --------------------------------------------------------
    # Ask for playlist ID
    # --------------------------------------------------------

    playlist_id = input(
        "Enter YouTube Playlist ID: "
    ).strip()


    if not playlist_id:

        print()
        print(
            "❌ No playlist ID provided."
        )
        print()

        exit(1)


    # --------------------------------------------------------
    # Store playlist ID
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


    # --------------------------------------------------------
    # Start Flask
    #
    # Disable automatic reloader so input()
    # does not execute twice.
    # --------------------------------------------------------

    app.run(
        debug=True,
        use_reloader=False
    )
