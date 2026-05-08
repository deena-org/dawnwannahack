# BizBuddy — Feature Inventory (Pre-PWA Improvements)

> Baseline snapshot before PWA enhancements. Compare against this after upgrades.

---

## Authentication
- MSME login via WhatsApp phone number (Firebase Firestore lookup)
- Bank portal login via access code (`bank2026`)
- Logout (clears session, returns to login screen)

## MSME Dashboard (Mobile View)
- Animated credit score circle (0–100, color-coded by tier)
- Score badge (Loan Ready / In Progress / Building / Not Scored)
- 4 stat cards: Total Revenue, Transactions, Avg per Sale, Best Sale
- Weekly growth trend indicators (↑ / ↓ vs last week) per stat
- Sales activity bar chart (7-day / 30-day / All-time toggle)
- Loan Readiness Roadmap (6-step progress bar)
- Score Breakdown card (6 AI-scored factors with bar visualization)
- Score History line chart (shows progression over time)
- Loan Pre-Qualification CTA (visible when score ≥ 70)
- Loan Pre-Qualification modal (summary + WhatsApp submit to bank)
- Recent Sales list (last 8 entries, screenshot vs chat icon)
- Credit Certificate card (star rating, cert ID, animated border)
- WhatsApp share button (share credit score via WA message)

## Bank Dashboard (Desktop View)
- 4 KPI stats: Total MSMEs, Loan Ready count, Avg Credit Score, Total Revenue
- Multi-currency revenue toggle (RM / Rp / ₱ with live conversion)
- MSME portfolio table (search, filter by status, pagination, row click modal)
- MSME detail modal (avatar, score, revenue, transactions, recent sales, phone)
- Score distribution bar chart (5 ranges)
- Portfolio doughnut chart (Loan Ready / In Progress / Building / Unscored)
- Revenue trends line chart (last 7 days, currency-aware)
- Loan Pipeline list (all score ≥ 70 MSMEs)
- ASEAN map (canvas-drawn, dot per MSME with color by score, hover tooltip)
- Impact Metrics section (onboarded count, total txn, loan-eligible, countries)
- Financial Inclusion progress bars (scored / banked / registered / tracking expenses)
- Country breakdown list (flag, MSME count, state count, loan-ready count)
- Export Report (generates printable HTML PDF via new tab)

## UX / UI
- Dark mode (default) + light mode toggle (persisted in localStorage)
- Bilingual: English / Bahasa Melayu toggle (persisted in localStorage)
- Animated counters on all numeric stats
- Slide-in modal animations
- Nav drawer (settings: refresh, theme, language, logout)
- Pull-to-refresh (mobile touch gesture)
- View toggle (My Dashboard ↔ Portfolio)
- Responsive layout (mobile + desktop breakpoints)

## PWA (Current State — Pre-Improvement)
- manifest.json: name, short_name, display standalone, theme/bg color only
- icons: none (`icons: []`)
- sw.js: install + activate only, no caching
- No install prompt
- No offline support
- No update notification

## Backend (app.py — separate, not in PWA scope)
- Flask webhook server for WhatsApp Business API
- Gemini AI integration for natural language financial tracking
- Firebase Firestore read/write
- Sales logging from chat + screenshot OCR
- Credit score calculation (6-factor AI scoring)
- Deployed on Render (Procfile)

## Tech Stack
| Layer | Tech |
|-------|------|
| Frontend | Vanilla JS (ES modules), HTML, CSS |
| Charts | Chart.js 4.4 (CDN) |
| Database | Firebase Firestore (CDN SDK) |
| Fonts | Google Fonts (Syne, DM Sans) |
| Backend | Python Flask + Gemini AI |
| Hosting | Static file server / Render |
| Auth | Phone number lookup (MSME) + hardcoded code (bank) |
