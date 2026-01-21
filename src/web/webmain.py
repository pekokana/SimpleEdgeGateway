import uvicorn
from src.common.config_loader import config

def main():
    # configからポート番号を取得。設定がない場合はデフォルト8000を使用
    webhost = config.web_host
    webport = config.web_port
    webreload = config.web_reload
    loglv = config.log_level
    
    print(f"Starting Web UI on http://{webhost}:{webport}")
    
    # appはFastAPIのインスタンスがあるパス（例: src.web.app:app）
    uvicorn.run(
        "src.web.app:app", 
        host=webhost, 
        port=webport, 
        reload=webreload,
        log_level=loglv.lower()
    )

if __name__ == "__main__":
    main()