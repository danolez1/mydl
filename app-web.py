from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yt_dlp

app = FastAPI()

class VideoURL(BaseModel):
    url: str

@app.post("/download")
async def download_video(video: VideoURL):
    url = video.url
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided")

    ydl_opts = {
        'format': 'best',
        'outtmpl': '%(title)s.%(ext)s',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return {"message": "Download started"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)