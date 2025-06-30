sudo apt update
# brew update
# brew upgrade
sudo apt install python3-pip nvm npm
pip3 install yt-dlp uvicorn "fastapi[standard]" --break-system-packages
npm install pm2 -g
pm2 start "fastapi dev app-web.py" --name "mydl"

chmod +x  /path/downloader/app-cli.py

nano ~/.zshrc

alias mydl='python3 /path/downloader/app-cli.py'
