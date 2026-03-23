# Random Sender Module

This project sends random portfolio weights to the QuantPhemes trading API during HKEX trading hours.

## What the script does

The script in `module1_random_sender.py`:

- Loads `API_KEY` and `STRATEGY_ID` from `.env`
- Uses timezone `Asia/Hong_Kong`
- Runs on weekdays only, every 5 minutes from `09:35` to `15:55` HKT
- Randomly selects a weight from:
  - `0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0`
- Sends holdings for one stock only:
  - `symbol: 2800.HK`

## API behavior

Base URL:

- `https://api.quantphemes.com`

Endpoint:

- `/api/v1/strategy/{strategyId}/holding`

Authentication:

- Bearer token using `Authorization: Bearer <API_KEY>`

Request method rules:

- First successful run of each day: `POST`
- Subsequent runs on the same day: `PATCH`
- Daily method state resets at midnight HKT

Payload rules:

- `POST` payload includes: `name`, `description`, `holdings`
- `PATCH` payload includes: `holdings` only

Each `holdings` entry contains:

- `effective_datetime`: current UTC time in ISO 8601 format
- `stocks`: one object
  - `symbol: 2800.HK`
  - `percentage: <random_weight>`

## Logging

The script logs to:

- Console
- Daily file: `logs/sender_YYYYMMDD.log`

Each API attempt logs:

- Timestamp (HKT)
- Weight sent
- Request type (`POST` or `PATCH`)
- HTTP status code
- Response body

## Error handling and retry

On HTTP or connection error:

- Log the error
- Retry once after 30 seconds
- If retry fails, log and skip that decision point
- Scheduler continues running (does not crash)

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Create or update `.env`:

```env
API_KEY=your_bearer_token
STRATEGY_ID=your_strategy_id
BASE_URL=https://api.quantphemes.com
```

Note: The script currently uses a fixed base URL constant in code.

## Run

```bash
python module1_random_sender.py
```

On startup, it prints a message with:

- timezone
- strategy ID
- next scheduled fire time

Working On Server:

```

sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

git clone <your-repo-url>
cd <your-repo-folder>

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.template .env
# edit .env with real API_KEY and STRATEGY_ID

python module1_random_sender.py

```