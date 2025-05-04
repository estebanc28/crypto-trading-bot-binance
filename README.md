# Crypto Trading Bot for Binance

This is an automated trading bot written in Python that operates on the Binance exchange. It uses a combination of EMA crossover strategy and RSI to generate trading signals on the DOGE/USDT pair with a scalping interval of 1 minute.

## 🔧 Features
- EMA Fast and Slow crossover strategy
- RSI indicator filter
- Market order execution via Binance API
- Real-time price monitoring
- Automated stop-loss and take-profit logic
- Trade logging to Excel
- Customizable parameters

## 📦 Installation

```bash
pip install -r requirements.txt
```

## 🚀 Usage

1. Create a `config.json` file with your Binance API keys:
```json
{
  "API_KEY": "your_api_key_here",
  "API_SECRET": "your_api_secret_here"
}
```

2. Run the bot:
```bash
python bot.py
```

## 📊 Example Strategy Logic
- Entry: EMA 9 > EMA 21 and RSI between 30 and 70
- Exit: TP at +2% or SL at -1%

## 💡 To-Do
- Backtesting module
- Strategy optimization using AI/ML
- Telegram alerts
- Web dashboard for live monitoring

## ⚠️ Disclaimer
This bot is for educational purposes only. Trading involves substantial risk and you are responsible for your own financial decisions.
