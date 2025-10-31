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
   - Paste your Odds API key and click **Test API** to validate it.
   - Select your desired regions, bookmakers, sports, markets, and deep markets.
   - Choose a time window preset or custom range, minimum edge percentage, bankroll, rounding increment, and per-book limits.
   - Configure scan mode (Snapshot, Continuous, or Burst) with the intervals you prefer.
   - Press **Save & Apply**.
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

With these steps you can install, update, and operate the ArbiSport scanner entirely from your Windows 11 machine.
