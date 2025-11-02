
---

## Menjalankan secara lokal (Windows PowerShell)
```powershell
cd "E:\Aplikasi Python\flask_pos_app"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FLASK_APP = "app.py"
flask run --host 0.0.0.0 --port 5000
```
