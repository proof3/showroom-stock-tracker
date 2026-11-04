# Showroom Stock Tracker

A small web app to record stock **purchased** and stock **allocated** (sent) to each showroom, by gender and category. Every entry is one line, and the app adds them up for you.

## What's in this folder

| File | What it does |
|---|---|
| `app.py` | The screens: Add entry, Summary, History, Categories, and the login |
| `database.py` | Everything that reads from or writes to the database |
| `requirements.txt` | The Python packages the app needs |
| `.streamlit/secrets.toml.example` | Template for passwords and the database address |
| `.gitignore` | Stops the real secrets file from being uploaded to GitHub |

## Who can do what

- **Viewers** can see Summary, History and Categories. They can't change anything.
- **Editors** can also add entries, correct or delete entries, and add or rename categories, genders and showrooms.

Passwords are set in the secrets file:
- `viewer_password` is one shared password for viewers. Leave it empty (`""`) if anyone with the link should be able to view.
- `[editors]` has one line per editor: `Name = "password"`. Each entry records the name of the editor who typed it.

---

## Part 1: Try it on your own computer (optional)

1. Install Python 3.10 or newer.
2. Open a terminal in this folder and run:
   ```
   pip install -r requirements.txt
   ```
3. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`. Set `url = ""` so it uses a local test file instead of Supabase, then set your passwords.
4. Run:
   ```
   streamlit run app.py
   ```
   The app opens in your browser. Test data is saved in `local_test_database.sqlite`. Delete that file to start fresh.

---

## Part 2: Put it online

You need three free accounts: **Supabase** (the database), **GitHub** (stores the code) and **Streamlit Community Cloud** (runs the app).

### Step 1: Get the database connection string (Supabase)

The Supabase project **showroom-stock-tracker** (region US West) has already been created, with the tables, the 11 showrooms and the starting genders loaded.

1. In Supabase, open **showroom-stock-tracker → Project Settings → Database** and click **Reset database password**. Choose a password and save it somewhere safe.
2. Click **Connect** at the top of the page.
3. Choose **Session pooler** and copy the connection string. It looks like:
   `postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-us-west-1.pooler.supabase.com:5432/postgres`
4. Replace `[YOUR-PASSWORD]` with the database password from step 1.

(If you ever start again with a brand-new, empty Supabase project, the app creates the tables and starting genders by itself the first time it runs. Showrooms are not stored in the code, so you would add them on the Categories screen under "Add a showroom".)

### Step 2: Put the code on GitHub

1. Sign up at https://github.com and create a new **private** repository (for example `showroom-stock-tracker`).
2. Upload `app.py`, `database.py`, `requirements.txt`, `.gitignore` and `README.md`.
3. **Do not upload `secrets.toml`.** It holds your passwords.

### Step 3: Run the app (Streamlit Community Cloud)

1. Go to https://share.streamlit.io and sign in with your GitHub account.
2. Click **Create app**, then choose your repository. Set the main file to `app.py`.
3. Open **Advanced settings → Secrets** and paste the contents of `secrets.toml.example`, filled in with:
   - the Supabase connection string from Step 1
   - the viewer password (or `""` for open viewing)
   - the editor names and passwords
4. Click **Deploy**. After a minute or two you'll get the app's link, ending in `.streamlit.app`.

### Step 4: Let people open it

An app made from a private GitHub repository starts as **private**: only people you invite by email can open it. You have two ways to share it:

- **Simplest:** in the app click **Share**, then make the app **public**. Anyone with the link reaches the login page, and the app's own viewer password protects the data.
- **Invite only:** keep it private and invite each person's email address from the **Share** button.

To change passwords or add an editor later, edit the **Secrets** in the app's settings on Streamlit Cloud. The app restarts with the new settings.

---

## Good to know

- **Sleeping:** free apps on Streamlit Cloud go to sleep when nobody uses them for a while. The first visitor sees a "wake up" button, and it takes about a minute.
- **Supabase free plan:** an unused free project can be paused after about a week with no activity. It's restored from the Supabase dashboard, and regular use keeps it active.
- **Backup:** on the Summary screen, pick the full date range and click **Download as Excel**. The "Entries" sheet holds every line ever entered. Doing this regularly keeps your own copy.
- **"Purchased but not yet allocated"** on the Summary screen is only correct if every purchase is entered, and if the purchase and its allocations fall inside the dates you picked.
- **Supabase's built-in Data API is switched off for these tables** (the app turns on "row level security"), so the data can only be reached through this app.
