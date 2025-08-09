from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import base64, hashlib, cloudscraper, time, os
from urllib.parse import urlparse

ORIGINAL_SECRET = "0TtN@v1.7.2AESk3y!"
ANDROID_ID = "dd96dec43fb6d99d"
PLAYLIST_URL = "https://ourimagine.my.id/adskdhajshlawuoaiwhoeh9aweowau2931aksdjnddka/mpd "

SECRET_KEY = hashlib.sha256(ORIGINAL_SECRET.encode()).digest()[:16]
IV = hashlib.sha256(ANDROID_ID.encode()).digest()[:16]

headers = {
    "User-Agent": "OTT Navigator/1.7.2 (Linux; Android 13; SM-G991B)",
    "X-OTT-Request": "1.7.2",
    "X-Android-ID": ANDROID_ID,
    "X-Timestamp": str(int(time.time() * 1000)),
    "Connection": "Keep-Alive",
    # Tambahan header yang sering digunakan app Android:
    "Accept": "*/*",
    "Accept-Encoding": "gzip",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

def ott_encrypt(data: str):
    cipher = AES.new(SECRET_KEY, AES.MODE_CBC, IV)
    padded_data = pad(data.encode(), AES.block_size)
    encrypted = cipher.encrypt(padded_data)
    return base64.b64encode(encrypted).decode()

def get_playlist():
    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'android', 'mobile': True}
        )

        signature = ott_encrypt(PLAYLIST_URL)
        print("Generated Signature:", signature)

        # Tampilkan URL awal
        print("URL Awal:", PLAYLIST_URL)

        resp = scraper.get(
            PLAYLIST_URL,
            headers={**headers, "X-Signature": signature},
            allow_redirects=False,
            timeout=15
        )
        print("Status Code Awal:", resp.status_code)

        if resp.status_code in [301, 302, 303, 307, 308]:
            redirect_url = resp.headers.get("Location", "")
            print("Redirect ditemukan ke:", redirect_url)

            if not redirect_url.startswith("http"):
                parsed_url = urlparse(PLAYLIST_URL)
                base = f"{parsed_url.scheme}://{parsed_url.netloc}"
                redirect_url = base + redirect_url

            # Tampilkan URL redirect lengkap
            final_url = f"{redirect_url}?did={ANDROID_ID}"
            print("URL Redirect Akhir:", final_url)

            final_resp = scraper.get(
                final_url,
                headers=headers,
                timeout=15
            )
            print("Status Code Final:", final_resp.status_code)
            return final_resp.text

        # Jika tidak redirect
        print("Tidak ada redirect, menggunakan URL asli")
        return resp.text

    except Exception as e:
        print(f"[ERROR] {e}")
        return None

if __name__ == "__main__":
    playlist = get_playlist()
    if playlist and "EXTM3U" in playlist:
        filename = "xyz.m3u"  # Nama file tetap
        with open(filename, "w", encoding="utf-8") as f:
            f.write(playlist)
        print("\n" + "="*50)
        print(f"Berhasil menyimpan playlist sebagai: {filename}")
        print(f"Jumlah channel: {playlist.count('#EXTINF:')}")
        print("="*50)
    else:
        print("\nGagal mendapatkan playlist. Cek kemungkinan:")
        print("- Signature tidak sesuai")
        print("- Redirect tidak valid")
        print("- ID Android tidak benar")
        print("- Timestamp tidak sinkron")
