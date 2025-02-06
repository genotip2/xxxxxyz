import requests

playlist_url = "https://bewe.gay/all"
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36'
}

try:
    response = requests.get(playlist_url, headers=headers)
    print(f"Status Code: {response.status_code}")  # Debug status server
    
    if response.status_code == 200:
        # Simpan playlist ke file untuk inspeksi manual
        with open("bewe.m3u", "w", encoding="utf-8") as f:
            f.write(response.text)
        print("Playlist disimpan sebagai bewe.m3u. Periksa file tersebut.")
        
        print("\nDaftar Saluran:")
        extinf_found = False
        for line in response.text.split('\n'):
            line = line.strip()
            if line.startswith('#EXTINF'):
                extinf_found = True
                channel_name = line.split(',')[-1] if ',' in line else "Nama tidak tersedia"
                print(channel_name)
        if not extinf_found:
            print("Tidak ada saluran yang ditemukan dalam playlist.")
    else:
        print(f"Gagal mengakses playlist. Kode status: {response.status_code}")
except Exception as e:
    print(f"Error: {e}")
