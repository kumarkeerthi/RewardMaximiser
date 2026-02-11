# RewardMaximiser on Azure VM (Step-by-Step Guide)

This guide explains how to deploy and host RewardMaximiser on an Azure Linux VM so you can access the app from Chrome.

---

## 1) Prerequisites

- Azure account
- SSH client (terminal on macOS/Linux, PowerShell or Windows Terminal on Windows)
- GitHub access to this repository

---

## 2) Create an Azure VM

1. Go to **Azure Portal** → **Virtual machines** → **Create**.
2. Pick:
   - **Image**: Ubuntu 22.04 LTS
   - **Size**: at least `Standard_B1ms` (2GB RAM recommended)
3. Authentication:
   - Prefer **SSH public key** (recommended)
4. Inbound ports:
   - Allow **SSH (22)**
   - You can allow **HTTP (80)** now, or add later in NSG.
5. Create VM and note:
   - **Public IP address**
   - **Username**

---

## 3) Open required ports in Network Security Group (NSG)

You have two options:

### Option A (recommended): use Nginx reverse proxy
Open only:
- `22` (SSH)
- `80` (HTTP)
- `443` (HTTPS, optional)

### Option B (quick direct app access)
Open:
- `22` (SSH)
- `8000` (RewardMaximiser app)

In Azure Portal:
1. VM → **Networking**.
2. Add inbound rules for ports if missing.

---

## 4) SSH into the VM

```bash
ssh <azure_username>@<vm_public_ip>
```

Example:

```bash
ssh azureuser@20.55.10.100
```

---

## 5) Install system dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx
```

If you plan HTTPS with Let’s Encrypt later:

```bash
sudo apt install -y certbot python3-certbot-nginx
```

---

## 6) Clone and set up RewardMaximiser

```bash
git clone <YOUR_REPO_URL> RewardMaximiser
cd RewardMaximiser
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

Install project dependencies (if any are added later):

```bash
pip install -e .
```

---

## 7) Seed data and refresh offers

```bash
PYTHONPATH=. python agent.py sync-cards --cards data/cards.sample.json
PYTHONPATH=. python agent.py --bank-offers data/bank_offers.sample.json --social-offers data/social_offers.sample.json refresh
```

You can replace sample files with your own card/offers data.

---

## 8) (Optional) Configure LLM integrations

### 8.1 Local Ollama (free, local model)
If Ollama is installed and running on VM, set model:

```bash
export OLLAMA_MODEL=llama3.1:8b
```

### 8.2 Hugging Face Inference (free tier limits)

```bash
export HF_API_KEY=<your_hf_token>
export HF_MODEL=mistralai/Mistral-7B-Instruct-v0.2
```

If no LLM endpoint is reachable, RewardMaximiser returns deterministic local summaries.

---

## 9) Run app once (smoke test)

```bash
PYTHONPATH=. python agent.py web --host 0.0.0.0 --port 8000
```

Now test in Chrome:
- Direct: `http://<vm_public_ip>:8000` (if port 8000 is open)

Press `Ctrl+C` after confirming it works.

---

## 10) Run app as a systemd service (recommended)

Create service file:

```bash
sudo tee /etc/systemd/system/rewardmaximiser.service >/dev/null <<'EOF'
[Unit]
Description=RewardMaximiser Web App
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/RewardMaximiser
Environment=PYTHONPATH=.
# Optional env vars for LLM providers:
# Environment=OLLAMA_MODEL=llama3.1:8b
# Environment=HF_API_KEY=replace_me
# Environment=HF_MODEL=mistralai/Mistral-7B-Instruct-v0.2
ExecStart=/home/$USER/RewardMaximiser/.venv/bin/python agent.py web --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

> If `$USER` does not expand correctly in your shell, replace with literal username (e.g. `azureuser`) before saving.

Reload and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable rewardmaximiser
sudo systemctl start rewardmaximiser
sudo systemctl status rewardmaximiser
```

View logs:

```bash
journalctl -u rewardmaximiser -f
```

---

## 11) Put Nginx in front (recommended for production)

Create Nginx site config:

```bash
sudo tee /etc/nginx/sites-available/rewardmaximiser >/dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
```

Enable and reload:

```bash
sudo ln -sf /etc/nginx/sites-available/rewardmaximiser /etc/nginx/sites-enabled/rewardmaximiser
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

Now access in Chrome:
- `http://<vm_public_ip>`

---

## 12) (Optional) Enable HTTPS with Let’s Encrypt

If you have a domain pointed to VM public IP:

```bash
sudo certbot --nginx -d <your-domain>
```

Follow prompts, then verify HTTPS works.

---

## 13) Ongoing operations

### Update code

```bash
cd ~/RewardMaximiser
git pull
source .venv/bin/activate
pip install -e .
sudo systemctl restart rewardmaximiser
```

### Refresh offers manually

```bash
cd ~/RewardMaximiser
source .venv/bin/activate
PYTHONPATH=. python agent.py --bank-offers data/bank_offers.sample.json --social-offers data/social_offers.sample.json refresh
```

### Back up SQLite DB

```bash
cp rewardmaximiser.db rewardmaximiser.db.bak
```

---

## 14) Troubleshooting checklist

- App not reachable:
  - Check NSG inbound rules (80/443/8000)
  - Check service status: `sudo systemctl status rewardmaximiser`
  - Check logs: `journalctl -u rewardmaximiser -f`
- Nginx bad gateway:
  - Confirm app is running on `127.0.0.1:8000`
  - Verify with `curl http://127.0.0.1:8000`
- Social scan empty:
  - Could be source-side changes/rate limits/network filtering
  - Recommendation engine still works with local data
- LLM output fallback only:
  - Ensure Ollama or HF credentials are configured and reachable

---

You now have a complete Azure VM deployment path for RewardMaximiser that is web-friendly and accessible in Chrome.
