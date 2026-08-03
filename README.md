# Evidence Desk

Evidence Desk (formerly Social Media Bias Auditor) is a browser extension and analytical backend designed to bring transparency and critical analysis to your social media consumption. By auditing the news sources in your Twitter/X feed against a massive 4-corpus fused dataset, Evidence Desk gives you a real-time, objective look at your information diet.

## Key Features

### 1. In-Feed Bias Detection
The Chrome extension seamlessly parses links and handles as you scroll, checking them against a proprietary fused dataset combining:
- **AllSides**
- **PABS** (Political Audience Bias Scores)
- **GDELT** (Global Database of Events, Language, and Tone)
- **Q-Bias**

### 2. The Evidence Desk Dashboard
A beautifully designed Bento-grid dashboard that provides deep, actionable analytics on your reading habits, focusing on calm, editorial clarity over alarmist metrics.
- **Information Nutrition Label:** Breaks down the "health" of your feed, similar to a food nutrition label.
- **2D Media Matrix:** Plots your recent exposures on a scatter plot comparing **Quality/Factuality** against **Political Bias (L/C/R)**.

### 3. Corroboration Spectrum & Story Clusters
Instead of simply labeling a single article as true or false, the backend queries Google News RSS to find alternate coverage of the same event.
- Stories are clustered by subject matter and assigned a **Verification Status**:
  - `Highly Verified` (Supported by multiple high-quality, cross-partisan sources)
  - `Establishment Verified` (Supported by mainstream center sources)
  - `Unverified` (Lacking alternate coverage)
  - `Contested (Echo Chamber)` (Only covered by highly polarized sources on one side of the spectrum)

### 4. Feed Rigidity Tracking
A statistical model tracks the variance of the bias scores you are exposed to.
- Low variance indicates a **High Rigidity** echo chamber.
- High variance indicates a **Diverse** and well-rounded feed.

---

## Architecture

- **Client:** A lightweight Manifest V3 Chrome Extension (Vanilla JavaScript). It handles DOM parsing (skipping known URL shorteners like `t.co`, `bit.ly`) and sends capture signals to the backend.
- **Backend:** A fast, asynchronous API built with **Python** and **FastAPI**. It handles state management, Google News alternate coverage lookups, and clustering logic.

---

## Getting Started

### 1. Deploying the Backend (Production)
The repository is pre-configured for automated deployment on **Render** (via `render.yaml`) or **Heroku/Railway** (via `Procfile`).

1. Connect this repository to your Render account.
2. Render will automatically detect the `render.yaml` file, install dependencies from `backend/requirements.txt`, and start the Uvicorn server.
3. Once deployed, copy your live URL (e.g., `https://evidencedesk-1.onrender.com`).

### 2. Configuring the Extension
1. Open `config.js` in the root of the project.
2. Update the `API_BASE_URL` to point to your live backend URL (or `http://localhost:8000` for local development).
   ```javascript
   const CONFIG = {
     API_BASE_URL: "https://evidencedesk-1.onrender.com"
   };
   ```

### 3. Installing the Extension
1. Open Google Chrome and navigate to `chrome://extensions/`.
2. Enable **Developer mode** in the top right corner.
3. Click **Load unpacked** and select the root folder of this repository (the folder containing `manifest.json`).
4. Pin the extension to your toolbar and start browsing Twitter/X!

---

## Local Development

If you want to run the backend locally instead of on a cloud provider:

```bash
# Navigate to the backend directory
cd backend

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the development server
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```
Then, ensure your `config.js` is set to `http://localhost:8000`.

---

## Testing & Artifact Evaluation
The backend includes a comprehensive test suite that populates the dashboard with realistic story clusters (Immigration, Federal Reserve, Tech/AI, Climate) to verify all features.

```bash
cd backend
python test_evidence_desk.py
```
*(Note: Ensure your local or remote server is running before executing the test script. It will automatically call the `/api/reset` endpoint to clear previous session data.)*

### Reproducing Paper Results
To reproduce the tables and figures from the "Real-Scale Evaluation" and "Longitudinal Resource Profiling" sections of the paper, we provide a unified reproducibility script.

1. Ensure Python dependencies are installed.
2. From the root directory, run:
```bash
./reproduce.sh
```
This script will:
- Generate a synthetic dataset of 250 captures simulating a continuous browsing session (`backend/scripts/generate_evaluation_dataset.py`).
- Run the companion service evaluation and print the latency percentiles and clustering metrics (`backend/scripts/evaluate_real_scale.py`).
- Generate the memory usage profiling graph and save it as `profiling_graph.png` (`backend/scripts/generate_profiling_graph.py`).
