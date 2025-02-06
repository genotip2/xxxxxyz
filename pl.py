import requests

# Pastikan URL diawali http:// atau https://
playlist_url = "http://boo.ourimagine.my.id/vdevr"  # Tanpa indentasi tidak perlu

try:
    response = requests.get(playlist_url)
    if response.status_code == 200:
        print("Daftar Saluran:")
        for line in response.text.split('\n'):
            if line.startswith('#EXTINF'):
                print(line.split(',')[-1].strip())
    else:
        print(f"Gagal mengakses playlist. Kode status: {response.status_code}")
except Exception as e:
    print(f"Error: {e}")
