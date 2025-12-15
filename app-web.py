from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import yt_dlp
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


class VideoURL(BaseModel):
    url: str
    type: str = "video"


def download(url, type="video"):
    logger.info(f"Processing URL: {url} with type: {type}")
    ydl_opts = {
        "outtmpl": "%(title)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        # "ignoreerrors": True, # Removed to catch exceptions properly
    }
    
    # Select format based on type
    # 'best' selects the best quality format that contains both video and audio.
    # 'bestaudio/best' selects the best audio-only format, or falls back to best video+audio.
    if type == "audio":
        ydl_opts["format"] = "bestaudio/best"
    else:
        ydl_opts["format"] = "best"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            
            if not info_dict:
                raise HTTPException(404, "Video info not found")

            # Handle playlists or search results
            if 'entries' in info_dict:
                entries = list(info_dict['entries'])
                if not entries:
                    raise HTTPException(404, "No videos found in playlist/search")
                info_dict = entries[0]

            # Get the download URL
            download_url = info_dict.get('url')
            
            if not download_url:
                # If 'url' is missing, it might be in 'requested_formats' (though usually 'best' resolves to one)
                logger.warning("Direct URL not found in info_dict, checking requested_formats or formats")
                # Sometimes yt-dlp puts the selected format in 'requested_downloads' or similar, 
                # but with download=False, it should be in 'url' or we inspect formats.
                # Let's try to fallback to iterating formats if yt-dlp didn't pick one cleanly in 'url'
                formats = info_dict.get('formats', [])
                if formats:
                    # Filter for progressive (video+audio) if type is video
                    if type == "video":
                        candidates = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
                        if candidates:
                            # Sort by resolution/bitrate
                            candidates.sort(key=lambda x: (x.get('height') or 0, x.get('tbr') or 0), reverse=True)
                            download_url = candidates[0].get('url')
                    else:
                        candidates = [f for f in formats if f.get('acodec') != 'none']
                        if candidates:
                            candidates.sort(key=lambda x: x.get('abr') or 0, reverse=True)
                            download_url = candidates[0].get('url')

            if not download_url:
                logger.error("Could not find a valid download URL")
                raise HTTPException(status_code=404, detail="Download URL not found")
            
            logger.info(f"Found download URL: {download_url[:50]}...")
            return download_url

    except Exception as e:
        logger.error(f"Error extracting info: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


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

    uvicorn.run(app, host="0.0.0.0", port=3000)
