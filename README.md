# ArbiSport Setup Guide

This project provides a desktop arbitrage scanner that connects to The Odds API, schedules scans, and surfaces profitable opportunities in a PySide6 GUI.

## Prerequisites
- **Windows 11** with administrator access (needed to install Python and Git).
- **Python 3.10 or newer.** Download from [python.org](https://www.python.org/downloads/windows/) and check the box labelled "Add Python to PATH" during installation.
- **Git for Windows.** Download from [git-scm.com](https://git-scm.com/download/win) and accept the defaults.

> **Tip:** After installing Python, open a fresh PowerShell window so the new `python` and `pip` commands are available.

## Fresh installation (no virtual environment)
1. Open **PowerShell** and choose a directory for the project, for example:
   ```powershell
   mkdir C:\Projects
   cd C:\Projects
   ```
2. Clone the latest version of this repository:
   ```powershell
   git clone https://github.com/LavaaC/ArbiSport.git
   cd ArbiSport
   ```
3. Upgrade `pip` (recommended) and install the app along with its dependencies directly into your user site-packages:
   ```powershell
   python -m pip install --upgrade pip
   python -m pip install --user -e .
   ```
   The editable install exposes the `arbisport` package locally while pulling in required libraries such as `requests` and `PySide6`.
4. (Optional) Run the automated tests to verify the install:
   ```powershell
   python -m pytest
   ```
5. Launch the desktop client:
   ```powershell
   python app.py
   ```

## Updating to the newest version
If you previously cloned the project and want the latest updates:
1. Open PowerShell in the existing project directory (e.g., `C:\Projects\ArbiSport`).
2. Pull the changes:
   ```powershell
   git pull
   ```
3. Re-run the install command to ensure new dependencies are captured:
   ```powershell
   python -m pip install --user -e .
   ```

## First run checklist
1. Start `python app.py` and wait for the PySide6 window to appear.
2. Navigate to the **Settings** tab:
   - Paste your Odds API key and click **Test API**. The app validates the key, downloads the live sports/bookmaker catalog, and falls back to the built-in list in `odds_client/catalog.py` if the network request fails.
   - Pick one or more **Regions** (US, UK, EU, AU). Region selection influences which bookmakers are shown when the catalog is filtered.
   - Multi-select the **Sports** you want to scan. Sports are labelled as `key — title` to match the Odds API documentation.
   - Multi-select the **Bookmakers** (pre-selected to “all” after a successful test). Use the list to enforce minimum book counts or per-book stake caps.
   - Choose the primary **Markets** (h2h, spreads, totals) and optionally provide comma-separated deep markets like `correct_score` or `set_totals`.
   - Set a **Time Window** using one of the presets (Next 2/6/24 hours) or enable custom start/end pickers for specific date ranges.
   - Define your bankroll configuration: minimum edge percentage, total bankroll, rounding increment, maximum stake per bookmaker, and minimum book count for a valid arbitrage.
   - Configure the scan mode (Snapshot, Continuous, Burst near start) and supply the interval settings.
   - Press **Save & Apply** to persist the configuration in the local SQLite database.
3. Use the toolbar buttons:
   - **Run Snapshot** performs a one-time scan based on your settings.
   - **Start** begins scheduled scanning; **Stop** halts it.
4. Monitor the **Dashboard**, **Arbitrage**, and **Logs** tabs for best prices, stake splits, alerts, and API usage headers. All scans are recorded in the local SQLite database `arbisport.db`.

## Common PowerShell questions
- **Execution policy prevents activating a virtual environment.** This setup skips virtual environments, so the policy warning can be ignored. If you later decide to use one, run PowerShell as Administrator and execute:
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```
- **`ModuleNotFoundError: No module named 'PySide6'`.** Ensure `python -m pip install --user -e .` completed successfully; rerun the command if necessary.
- **Editable install reports “Multiple top-level packages discovered”.** Confirm your `pyproject.toml` contains the `[tool.setuptools]` section listing `arb_engine`, `controller`, `normalize`, `odds_client`, `persistence`, and `ui`. If the block is missing (for example after resolving a merge), restore it with `git checkout -- pyproject.toml` or merge the latest `main`. Also make sure your setuptools version is 61 or newer: `python -c "import setuptools; print(setuptools.__version__)"`.

With these steps you can install, update, and operate the ArbiSport scanner entirely from your Windows 11 machine.

## Sports and bookmaker reference

The complete catalogue used by the UI lives in [`odds_client/catalog.py`](odds_client/catalog.py). Each entry mirrors the Odds API’s `key` values so you can copy selections directly into API requests if needed. Highlights include:

- **American Football:** `americanfootball_nfl`, `americanfootball_ncaaf`, `americanfootball_cfl`, `americanfootball_ufl`, `americanfootball_xfl`
- **Basketball:** `basketball_nba`, `basketball_ncaab`, `basketball_wnba`, `basketball_euroleague`, `basketball_nbl`, `basketball_fiba`
- **Baseball:** `baseball_mlb`, `baseball_kbo`, `baseball_npb`, `baseball_us_college`
- **Ice Hockey:** `icehockey_nhl`, `icehockey_sweden_shl`, `icehockey_sweden_allsvenskan`, `icehockey_russia_khl`, `icehockey_finnish_liiga`
- **Soccer:** Premier leagues and cups across Europe, North/South America, Asia, and international tournaments (`soccer_epl`, `soccer_spain_la_liga`, `soccer_usa_mls`, `soccer_fifa_world_cup`, `soccer_uefa_champions_league`, and many more)
- **Tennis:** Tour-level and major-specific keys for ATP and WTA (`tennis_atp`, `tennis_wta`, `tennis_atp_us_open`, `tennis_wta_wimbledon`, etc.) along with ITF and Challenger circuits
- **Other:** AFL, cricket tournaments (IPL, Big Bash, PSL), rugby leagues, golf majors, motorsport, MMA/boxing, esports, darts, table tennis, and snooker

Bookmakers are similarly catalogued with region coverage (e.g., `betmgm`, `fanduel`, `draftkings`, `bet365`, `pinnacle`, `ladbrokes`, `pointsbetus`, `williamhill_uk`, `wynnbet`). The **Settings → Test API** workflow automatically filters the list to the regions you select while keeping the full catalogue available for manual overrides.
