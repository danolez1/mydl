from utils import pick_best
import yt_dlp
import json


def download(url, type="video"):
    ydl_opts = {
        "outtmpl": "%(title)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
    }

    if type == "audio":
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",  # “0” = best
            }
        ]

    if "youtube" not in url:
        ydl_opts["format"] = "best"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        if "youtube" not in url:
            ydl.download([url])
            return
            
        info_dict = ydl.extract_info(url, download=False)
        formats = info_dict.get("formats", None)
        best_video_fmt, best_audio_fmt = pick_best(formats)

        if type == "video":
            ydl.download([best_video_fmt["url"]])
        elif type == "audio":
            ydl.download([best_audio_fmt["url"]])


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "help":
            print("Usage: python app-cli.py <url> [video|audio]")
            print(
                "Example: python app-cli.py https://www.youtube.com/watch?v=dQw4w9WgXcQ video"
            )
            print(
                "Example: python app-cli.py https://www.youtube.com/watch?v=dQw4w9WgXcQ audio"
            )

        elif len(sys.argv) > 2:
            if sys.argv[2] == "video":
                download(sys.argv[1], "video")
            elif sys.argv[2] == "audio":
                download(sys.argv[1], "audio")
            else:
                print("Invalid type. Use 'video' or 'audio'.")
        else:
            download(sys.argv[1])
    else:
        print("Please provide a URL.")
