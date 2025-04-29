from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from utils import pick_best
import yt_dlp

app = FastAPI()


class VideoURL(BaseModel):
    url: str


def download(url, type="video"):
    ydl_opts = {
        "outtmpl": "%(title)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=False)
        formats = info_dict.get("formats", None)
        best_video_fmt, best_audio_fmt = pick_best(formats)

        if type == "video":
            return best_video_fmt["url"]
        elif type == "audio":
            return best_audio_fmt["url"]


@app.post("/download")
async def get_download_url(video: VideoURL):
    url = video.url
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided")

    return {"download_url": download(url, "video")}


@app.get("/", response_class=HTMLResponse)
async def get_download_url(url: str, type: str = "video"):
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided")

    return (
        """
    <html>
        <head>
            <title>Download</title>
        </head>
        <body>
            <a href="""
        + download(url, type)
        + """>Download</a>
        </body>
    </html>
    """
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
