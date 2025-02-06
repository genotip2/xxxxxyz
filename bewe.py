import requests
import cloudscraper  # Install dulu: pip install cloudscraper

playlist_url = "https://bewe.gay/all"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.google.com/',
    'DNT': '1',  # Do Not Track
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-site'
}
try:
    # Coba dengan cloudscraper (jika ada anti-bot)
    scraper = cloudscraper.create_scraper()
    response = scraper.get(playlist_url, headers=headers)
    
    # Jika tetap error, coba dengan requests + proxy
    # response = requests.get(playlist_url, headers=headers, proxies=proxies)
    
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        with open("bewe.m3u", "w", encoding="utf-8") as f:
            f.write(response.text)
        print("Playlist disimpan sebagai bewe.m3u.")
        
        print("\nDaftar Saluran:")
        for line in response.text.split('\n'):
            line = line.strip()
            if line.startswith('#EXTINF'):
                channel_name = line.split(',')[-1] if ',' in line else "N/A"
                print(channel_name)
    else:
        print(f"Gagal mengakses. Kode: {response.status_code}")
except Exception as e:
    print(f"Error: {e}")
