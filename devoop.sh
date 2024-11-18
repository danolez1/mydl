sudo apt update
sudo apt install python3-pip nvm npm
pip3 install yt-dlp --break-system-packages
pip install "fastapi[standard]" --break-system-packages
pip install fastapi --break-system-packages
pip install uvicorn --break-system-packages
npm install pm2 -g
pm2 start "fastapi dev app-web.py" --name "downloader"

chmod +x  /path/downloader/app-cli.py

nano ~/.zshrc

alias mydl='python3 /path/downloader/app-cli.py'