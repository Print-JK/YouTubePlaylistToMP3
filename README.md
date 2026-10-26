
  <h1>🎵 YouTube Playlist to MP3 Downloader (Flask App)</h1>

  <p>This Flask app allows you to:</p>
  <ul>
    <li>Authenticate with your <strong>Google account</strong></li>
    <li>Access your <strong>YouTube "Liked Videos"</strong></li>
    <li>Save video titles to a CSV</li>
    <li>Download videos as <strong>MP3s</strong> into your Downloads folder</li>
  </ul>

  <h2>🚀 Features</h2>
  <ul>
    <li>🔐 OAuth 2.0 login with Google</li>
    <li>📄 Exports playlist videos based on playlist id to <code>songs.csv</code></li>
    <li>🎧 Downloads each video as MP3</li>
    <li>📁 Files saved to <code>~/Downloads/songs/</code></li>
  </ul>

  <h2>🛠 Requirements</h2>
  <ul>
    <li>Python 3.8+</li>
    <li><code>ffmpeg</code> installed and accessible</li>
    <li>Google Cloud project with OAuth 2.0 credentials</li>
  </ul>

  <h2>📦 Setup Instructions</h2>

## 1. Clone or Download the Project

If you are using Git:
```
git clone https://github.com/Print-JK/YouTubePlaylistToMP3.git
cd YouTubePlaylistToMP3
```

Or simply download the project ZIP and extract it.

## 2. Create a Python Virtual Environment

Open a terminal inside the project folder.

### Linux / macOS
```
python3 -m venv venv

# Activate it:
source venv/bin/activate
```

### Windows
```
python -m venv venv


# Activate it:

venv\Scripts\activate
```

## 3. Install Python Dependencies

With the virtual environment activated:

```pip install flask yt-dlp pandas google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2```


## 4. Install FFmpeg

FFmpeg is required because yt-dlp downloads the audio and then converts it to MP3.

### Linux / Ubuntu / Debian
```
sudo apt update
sudo apt install ffmpeg
```

### Windows

Install FFmpeg and make sure the ffmpeg executable is available in your system PATH.

Then open a new terminal and run:
```
ffmpeg -version
```

If the command displays FFmpeg information, it is installed correctly.

## 5. Create a Google Cloud Project

Go to Google Cloud Console:

https://console.cloud.google.com/

Create a new project.

For example:

YouTube Playlist Downloader

## 6. Enable the YouTube Data API

Inside your Google Cloud project:

Open APIs & Services
Select Library
Search for:
YouTube Data API v3

Open it
Click Enable
## 7. Configure the OAuth Consent Screen

Go to:

Google Cloud → APIs & Services → OAuth consent screen

Configure the application.

For a personal project, you can generally use:

User type: External


Fill in the required application information.

You will need to provide an application name and your email information.

## 8. Add Yourself as a Test User

If your OAuth application is in testing mode:

Open the OAuth consent screen
Find Test users
Click Add users
Add the Google account that owns the YouTube playlist you want to access

For example:

your-email@gmail.com


This is important. If your account isn't listed as a test user, Google may prevent authentication.

## 9. Create OAuth Credentials

Go to:

Google Cloud → APIs & Services → Credentials

Click:

Create Credentials → OAuth client ID

Select:

Application type:
Web application


Give it a name, for example:

YouTube Playlist Downloader

## 10. Configure the Redirect URI

Your Flask application uses:

/redirect


The default Flask development server runs on:

http://127.0.0.1:5000


Therefore, add this as an authorized redirect URI:

http://127.0.0.1:5000/redirect


If you use localhost instead, you can use:

http://localhost:5000/redirect


Make sure the URI in Google Cloud matches the URI used by the application.

## 11. Download client_secrets.json

After creating the OAuth client:

Download the JSON credentials file.
Rename it to:
client_secrets.json

Place it in the root directory of the project.

Your project should look approximately like this:
```
YouTubePlaylistToMP3/
│
├── app.py
├── client_secrets.json
├── README.md
│
└── venv/
```


If client_secrets.json has already been uploaded to a public repository, create new OAuth credentials and revoke the old ones.

## 12. Get Your YouTube Playlist ID

Open the YouTube playlist you want to download.

A playlist URL looks like:

https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxx


The playlist ID is the value after:

list=


For example:

https://www.youtube.com/playlist?list=PL123456789


The playlist ID is:

PL123456789

You can paste either the full playlist link or just the playlist ID.

## 13. Run the Application

run:

```python app.py```


You should see:
```
============================================================
YouTube Playlist → MP3
============================================================

Enter YouTube Playlist Link or ID:

PL123456789

Using playlist: PL123456789

Starting Flask...

```
The application will then start Flask.

## 14. Open the Application

Open your browser and go to:

http://127.0.0.1:5000


Google will ask you to sign in.

Sign in using the Google account that has access to the playlist.

After authorization, the application will retrieve the playlist videos, print all titles once, and ask how you want to download:

```
Videos in playlist:
------------------------------------------------------------
[1] Song A - Artist A
     https://www.youtube.com/watch?v=abc123
[2] Song B - Artist B
     https://www.youtube.com/watch?v=def456
...
------------------------------------------------------------

How do you want to download?
  all   - download the entire playlist
  num   - download the first N videos
  after - download the videos after a video number or video title
>
```

Choose one of:

- `all` — download every video in the playlist
- `num` — download only the first N videos (you will be asked for N)
- `after` — download the videos that come after a video number or video title

For example, typing `num` then `2` downloads only the first 2 videos.

Typing `after` then `3` downloads videos 4, 5, 6, ... to the end of the playlist.

Typing `after` then `alpha` downloads every video that comes after the first video with "alpha" in its title.

## 15. Where Are the MP3 Files?

The MP3 files are saved here:

Linux / macOS
`~/Downloads/songs/`

Windows
`C:\Users\YOUR_USERNAME\Downloads\songs\`


The application creates the songs directory automatically.

## 16. Download Tracking

The application creates:

`~/Downloads/songs.csv`


The CSV contains:

title
channel
video_id
url
status
error


For example:

title,channel,video_id,url,status,error
Song A,Artist A,abc123,https://youtube.com/watch?v=abc123,Downloaded,
Song B,Artist B,def456,https://youtube.com/watch?v=def456,Downloaded,
Song C,Artist C,cvCFRGn7EEQ,https://youtube.com/watch?v=cvCFRGn7EEQ,Failed,"Video unavailable"


Possible statuses are:

Pending
Downloading
Downloaded
Failed

## 17. Failed Downloads

If a video cannot be downloaded, the application will not stop the entire playlist.

For example:

[37/100] Some unavailable video
❌ Failed: Some unavailable video
   Reason: ERROR: [youtube] cvCFRGn7EEQ: Video unavailable


The application will then continue:

[38/100] Next video
✅ Downloaded: Next video


The failed video will be recorded in songs.csv.

##  18. Updating yt-dlp

YouTube changes frequently, so keeping yt-dlp updated is recommended.

With the virtual environment activated:

```pip install -U yt-dlp```

If downloads suddenly stop working, updating yt-dlp should be one of the first troubleshooting steps.
  <h2>⚠️ Limitations</h2>
  <ul>
    <p>It is recommended that each download session is limited to only 400-500 videos, and take around a 6-12 hrs break before starting a new download session to avoid CAPTCHAs</p>
     </ul>



  <h2>🧠 Credits</h2>
  <ul>
    <li>Flask – Web framework</li>
    <li>yt-dlp – YouTube downloader</li>
    <li>YouTube Data API – Liked video fetch</li>
    <li>pandas – CSV writing</li>
    <li>youtubesearchpython – Video search</li>
    <li>Wong Wei Jun - YoutubeLikedVidsToMP3</li>
  </ul>

  <h2>⚠️ Legal</h2>
  <p>This tool is for <strong>educational and personal use only</strong>. Respect copyright laws and YouTube’s terms of service.</p>


</body>
</html>








