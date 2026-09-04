# RailETA Public Website — Deployment

1. GitHub.com par login karo aur `rail-eta` naam ka repository banao.
2. Is folder ki saari files upload karo.
3. Render.com par login karo.
4. New -> Web Service -> apni GitHub repository select karo.
5. Build Command:
   `pip install -r requirements.txt`
6. Start Command:
   `gunicorn app:app`
7. Deploy karo.
8. Deploy ke baad Render ek HTTPS public link dega, jaise:
   `https://rail-eta.onrender.com`

Is link ko kisi bhi mobile/laptop se open kiya ja sakta hai.

Note: Current prototype simulated train data + SQLite use karta hai. Hosting restart/redeploy par SQLite changes reset ho sakte hain. Permanent data ke liye PostgreSQL recommended hai.
