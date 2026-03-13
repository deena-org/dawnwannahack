# BizBuddy
AI-Powered WhatsApp Assistant for Inclusive MSME Growth in ASEAN

---

# Overview

BizBuddy is an AI-powered WhatsApp assistant designed to help Micro, Small, and Medium Enterprises (MSMEs) access digital tools, financial insights, and credit opportunities.

Many MSMEs across ASEAN operate informally, without access to banking systems, financial analytics, or export knowledge. BizBuddy addresses this gap by providing a conversational AI interface that enables businesses to:

• Record daily sales  
• Generate alternative credit scores  
• Receive AI-powered business advice  
• Understand export opportunities within ASEAN  

By using WhatsApp — a platform already widely used by small business owners — BizBuddy lowers the barrier to digital adoption and financial inclusion.

This project was developed for the **AI for Inclusive MSME Growth** case study.

---

# Team

Adam
Ajwad  
Sakinah  
Deena  
Dawna  

---

# Demo Video

Watch the project demo here:

https://youtu.be/jK9j5gp6vFk

---

# GitHub Repository

https://github.com/deena-org/dawnwannahack.git

---

# How BizBuddy Solves the Case Study

The case study highlights three major barriers faced by MSMEs:

### 1. Limited Access to Financing

Many MSMEs lack formal financial records required by banks.

BizBuddy solves this by:

• Recording daily sales through WhatsApp  
• Building a transaction history  
• Generating an **AI-powered alternative credit score**

This helps lenders assess MSME creditworthiness even without formal banking records.

---

### 2. Lack of Digital Capabilities

Many small businesses cannot afford complex digital tools.

BizBuddy solves this by providing:

• A **WhatsApp-based interface** (no app installation required)  
• Simple chat commands to log sales and request insights  
• AI-powered business advice in natural language

This allows MSMEs to access enterprise-grade analytics through a familiar messaging platform.

---

### 3. Difficulty Entering Regional Markets

Cross-border trade regulations are difficult for small businesses to navigate.

BizBuddy addresses this through:

• An **AI-generated ASEAN Export Guide**
• Guidance based on the ASEAN Free Trade Area (AFTA)
• Market entry insights for regional expansion

This empowers MSMEs to explore cross-border opportunities across ASEAN.

---

# Key Features

### WhatsApp MSME Onboarding
Businesses can register directly through WhatsApp with a simple conversational flow.

---

### Sales Recording
MSME owners can log daily sales transactions via chat.

Example:
Record sale 150

This transaction data is stored and used for analytics and credit scoring.

---

### AI Credit Scoring
BizBuddy analyzes informal transaction data to generate an **alternative credit score** that estimates loan readiness.

Example output:
Credit Score: 70 / 100
Status: Loan Ready


---

### AI Business Advisor
Using Google's Gemini AI, the bot provides personalized business advice such as:

• Growth strategies  
• Pricing suggestions  
• Operational improvements  

---

### ASEAN Export Guide
BizBuddy generates AI-powered export guidance based on ASEAN trade frameworks, helping MSMEs explore regional markets.

---

### Social Media Content Generator
BizBuddy generates AI-powered marketing content for social media platforms including:

• Instagram captions  
• WhatsApp Blast messages  
• TikTok video scripts  
• Facebook posts  
• Seasonal promotion ideas  

---

### AI Sales Forecast
BizBuddy analyzes recorded transaction data to generate a 30-day sales forecast, identifying top-performing products and sales trends.

---

### AI Supply Chain Tips
BizBuddy provides AI-generated supply chain and inventory recommendations based on the business's cash flow and product data.

---

### Multilingual Support
The system supports:

• English  
• Bahasa Melayu  

This improves accessibility for diverse MSME communities.

---

# Web Dashboard

The included `index.html` dashboard provides a visual interface for monitoring MSME activity.

Features include:

### MSME Insights Map
Displays the geographic distribution of registered businesses.

---

### Credit Score Visualization
Shows MSME credit scores and loan readiness categories:

• Loan Ready  
• In Progress  
• Building  

---

### Revenue Analytics
Aggregates sales data and displays revenue trends.

---

### Portfolio Oversight
Stakeholders can view:

• Business owner name  
• Business type  
• Location  
• Performance metrics  

---

# System Architecture

BizBuddy integrates multiple technologies to deliver an AI-driven ecosystem.

User → WhatsApp  
↓  
WhatsApp Cloud API  
↓  
Flask Backend (Python)  
↓  
Firebase Firestore Database  
↓  
Gemini AI Engine  

The backend processes incoming WhatsApp messages, stores transaction data, and generates AI-powered responses.

---

# Tech Stack

Backend  
Python (Flask)

Frontend  
HTML / CSS / JavaScript  
Chart.js (for analytics)

Database  
Firebase Firestore

AI Engine  
Google Gemini API (Gemini 2.5 Flash)

Communication  
WhatsApp Cloud API

Infrastructure  
Railway (Backend Hosting)  
GitHub (Version Control)

Other Tools  
python-dotenv  
google-generativeai SDK

---

# Hosted WhatsApp Bot

The WhatsApp bot is currently deployed using Railway.

Deployment Date  
13 March 2026

Remaining Free Tier Runtime  
Approximately 20 days from deployment.

This hosted deployment allows judges to test the bot without running the project locally.

---

# Testing the WhatsApp Bot

Send a message to the WhatsApp test number:

+1 (555) 664-8532

Start by sending:
Hi


The bot will respond with the BizBuddy menu.

---

# WhatsApp API Restriction

Due to restrictions from the Meta WhatsApp Cloud API development environment, only approved test numbers can interact with the bot.

If you would like to test the system:

1. Send your WhatsApp number for verification
2. Your number will be added to the Meta Developer test users list
3. After approval, you can interact with the bot normally

Verification Contact:

+60 19-594 7322

---

# Running the Project Locally

If evaluators wish to run the system locally, follow these steps.

---

# 1 Clone the Repository
git clone https://github.com/deena-org/dawnwannahack.git
cd dawnwannahack

---

# 2 Install Dependencies

Ensure Python 3.9 or later is installed.

Install the required packages:
pip install flask firebase-admin python-dotenv requests google-generativeai

---

# 3 Create Environment Variables

Create a `.env` file and add the following variables:
VERIFY_TOKEN=your_verify_token
WHATSAPP_TOKEN=your_whatsapp_token
PHONE_NUMBER_ID=your_phone_number_id
GEMINI_API_KEY=your_gemini_api_key
FIREBASE_CREDENTIALS_BASE64=your_firebase_credentials

These credentials are obtained from:

• Meta WhatsApp Cloud API  
• Google Gemini API  
• Firebase Service Account

---

# 4 Run the Backend Server

Start the Flask server:
python app.py

The server will start listening for WhatsApp webhook events.

---

# 5 Expose the Server

WhatsApp requires a public HTTPS endpoint.

You can use a tunneling tool such as:
ngrok http 5000

This will generate a public URL such as:
https://xxxx.ngrok.io

Use this URL when configuring the WhatsApp webhook in the Meta Developer dashboard.

---

# 6 Open the Dashboard

Open the dashboard file in your browser:
index.html

---

# AI Disclosure

This project integrates artificial intelligence to enhance MSME support services.

AI is used for the following components:

AI Business Advisor  
Generated using Google Gemini API (Gemini 2.5 Flash). Provides real-time, context-aware business advice, revenue forecasting, and supply chain tips tailored to each MSME's cash-flow data.

Receipt OCR (Multimodal Vision)  
Gemini's multimodal capabilities are used to automatically extract financial data from user-uploaded receipt images, enabling sales to be recorded without manual typing.

Natural Language Processing  
Gemini converts unstructured WhatsApp chat messages (e.g. "sold 2 karipap for RM1") into structured ledger entries, automating bookkeeping for micro-entrepreneurs.

Credit Score Insights  
Gemini assists in interpreting transaction data and generating bilingual explanations for credit scores.

Export Guide Generation  
Gemini generates region-specific market entry recommendations based on ASEAN trade frameworks.

Social Media Content Generation  
Gemini generates platform-specific marketing content (Instagram captions, TikTok scripts, WhatsApp blasts) based on the business's product and promotion details.

All financial transaction data and credit score calculations are stored and managed using Firebase Firestore.

AI outputs are used as decision-support tools and not as authoritative financial advice.

---

# Future Improvements

Potential future enhancements include:

• Integration with digital payment platforms  
• Automated inventory management  
• Predictive demand forecasting  
• Bank and microfinance integrations  
• Multi-country regulatory compliance modules  

---

# License

This project was created for a hackathon and educational purposes.