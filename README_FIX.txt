RAILPACK FIX - Hosting-Dev
==========================
1. Is ZIP ki 2 files repo ke ROOT mein daalo (purani railway.json replace karo):
     railway.json
     railpack.json
2. Repo se ye 2 files DELETE karo:
     nixpacks.toml
     Procfile
3. Commit + push karo. Railway khud Railpack se build karega.

Notes:
- /health healthcheck hata diya, kyunke main.py mein HTTP server nahi hai.
- Node 20 .js script support ke liye add kiya hai.
- Agar build mein gcc / wheel compile error aaye, railpack.json mein ye line add karo:
    "buildAptPackages": ["gcc", "libc6-dev"],
