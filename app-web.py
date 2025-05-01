from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from utils import pick_best
import yt_dlp

app = FastAPI()


class VideoURL(BaseModel):
    url: str
    type: str = "video"


def download(url, type="video"):
    ydl_opts = {
        "outtmpl": "%(title)s.%(ext)s",
        "quiet": True,
        "ignoreerrors": True,
        "no_warnings": True,
    }
    
    if "youtube" not in url:
        ydl_opts["format"] = "best"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=False)
        if not info_dict or "formats" not in info_dict:
            raise HTTPException(404, "Video not found or unavailable")
        
        if "youtube" not in url:
            download_url = info_dict.get('url', None)
            if not download_url:
                raise HTTPException(status_code=404, detail="Download URL not found")
            return download_url
        
        best_video_fmt, best_audio_fmt = pick_best(info_dict["formats"])

        if type == "video":
            return best_video_fmt["url"]
        elif type == "audio":
            return best_audio_fmt["url"]


@app.post("/download")
async def get_download_url(video: VideoURL):
    url = video.url
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided")

    return {"download_url": download(url, video.type)}

templates = Jinja2Templates("templates")

@app.get("/", response_class=HTMLResponse)
async def get_download_url(request: Request, url: str, type: str = "video"):
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided")

    try:
        dl_url = download(url, type)
    except HTTPException as exc:
        raise exc
    return templates.TemplateResponse(
        "download.html",
        {"request": request, "dl_url": dl_url}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
