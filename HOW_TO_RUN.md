# How to Run Locally

## Prerequisites

Install **Python 3** — https://www.python.org/downloads/

During install on Windows: check **"Add Python to PATH"**

Verify install:
```
python --version
```

---

## Steps

**1. Clone the repo**
```
git clone https://github.com/deena-org/dawnwannahack.git
```

**2. Go into the folder**
```
cd dawnwannahack
```

**3. Start local server**
```
python -m http.server 8080
```

**4. Open browser**

Go to: `http://localhost:8080`

**5. Stop server**

Press `Ctrl+C` in terminal.

---

## Login

- **MSME view** — enter your registered WhatsApp number
- **Bank view** — enter access code `bank2026`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `python` not found | Use `python3 -m http.server 8080` instead |
| Page loads but no data | Make sure you're on `http://localhost:8080`, not opening the file directly |
| Port already in use | Change port: `python -m http.server 3000` then open `http://localhost:3000` |
