import requests

   # Ganti dengan path file lokal atau URL yang legal
   playlist_url = "http://example.com/playlist.m3u"

   try:
       response = requests.get(playlist_url)
       if response.status_code == 200:
           print("Daftar Saluran:")
           for line in response.text.split('\n'):
               if line.startswith('#EXTINF'):
                   print(line.split(',')[-1].strip())
       else:
           print("Gagal mengakses playlist.")
   except Exception as e:
       print(f"Error: {e}")
