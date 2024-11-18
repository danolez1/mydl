from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yt_dlp

app = FastAPI()

class VideoURL(BaseModel):
    url: str

@app.post("/download")
async def get_download_url(video: VideoURL):
    url = video.url
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided")

    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=False)
        download_url = info_dict.get('url', None)
        if not download_url:
            raise HTTPException(status_code=404, detail="Download URL not found")

    return {"download_url": download_url}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)