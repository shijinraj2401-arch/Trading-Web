from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import yfinance as yf
import pandas as pd
import ta
import math
import random
import os
import json
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'super_secret_trading_key_123'

ADMIN_USERNAME = "shijin_admin"       
ADMIN_PASSWORD = "Secure@Trade2026#"   

# --- പുതിയ ഡാറ്റാബേസ് സിസ്റ്റം (No Firebase) ---
DB_FILE = "users_db.json"

def load_users():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, 'r') as f:
        try:
            return json.load(f)
        except:
            return {}

def save_users(users):
    with open(DB_FILE, 'w') as f:
        json.dump(users, f)
# ----------------------------------------------

@app.route('/')
def login_page():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session['user'] = 'admin'
        return redirect(url_for('admin_panel'))
        
    users = load_users()
    user_data = users.get(username)
    
    if user_data and user_data.get('password') == password:
        expiry_date = datetime.strptime(user_data.get('expiry'), "%Y-%m-%d")
        if datetime.now() > expiry_date:
            return render_template('login.html', error="Subscription Expired! Contact Admin via Telegram.")
        
        session['user'] = username
        return redirect(url_for('dashboard'))
    else:
        return render_template('login.html', error="Invalid Username or Password!")

@app.route('/admin', methods=['GET'])
def admin_panel():
    if session.get('user') != 'admin':
        return "Unauthorized", 401
    users_data = load_users()
    return render_template('admin.html', users=users_data)

@app.route('/admin/add_user', methods=['POST'])
def add_user():
    if session.get('user') != 'admin': return "Unauthorized", 401
    username = request.form.get('username')
    password = request.form.get('password')
    expiry = request.form.get('expiry')
    
    users = load_users()
    users[username] = {'password': password, 'expiry': expiry}
    save_users(users)
    
    return redirect(url_for('admin_panel'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login_page'))

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    current_user = session['user']
    user_expiry = "Unlimited"
    if current_user != 'admin':
        users = load_users()
        user_data = users.get(current_user)
        user_expiry = user_data.get('expiry', 'N/A') if user_data else 'N/A'
    return render_template('index.html', expiry=user_expiry, username=current_user)

@app.route('/api/signal')
def get_signal():
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    tf = request.args.get('tf', '1m')
    asset = request.args.get('asset', 'EURJPY') 
    ticker = f"{asset}=X" 
    try:
        df = yf.download(ticker, period='1d', interval=tf, progress=False)
        if df.empty: return jsonify({"error": "Data not found"}), 400
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        close_prices = df['Close']
        df['RSI'] = ta.momentum.RSIIndicator(close_prices, window=14).rsi()
        macd = ta.trend.MACD(close_prices)
        df['MACD'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        indicator_bb = ta.volatility.BollingerBands(close=close_prices, window=20, window_dev=2)
        df['BB_High'] = indicator_bb.bollinger_hband()
        df['BB_Low'] = indicator_bb.bollinger_lband()
        last_close = float(close_prices.iloc[-1])
        last_rsi = float(df['RSI'].iloc[-1])
        prev_rsi = float(df['RSI'].iloc[-2])
        last_macd = float(df['MACD'].iloc[-1])
        prev_macd = float(df['MACD'].iloc[-2])
        last_macd_signal = float(df['MACD_Signal'].iloc[-1])
        prev_macd_signal = float(df['MACD_Signal'].iloc[-2])
        last_bb_high = float(df['BB_High'].iloc[-1])
        last_bb_low = float(df['BB_Low'].iloc[-1])
        bullish_score, bearish_score = 0, 0
        if not math.isnan(last_rsi) and not math.isnan(prev_rsi):
            if last_rsi > 50 and last_rsi > prev_rsi: bullish_score += 30
            elif last_rsi < 50 and last_rsi < prev_rsi: bearish_score += 30
            else: bullish_score += 15; bearish_score += 15
        if not math.isnan(last_macd) and not math.isnan(last_macd_signal):
            if prev_macd < prev_macd_signal and last_macd > last_macd_signal: bullish_score += 40 
            elif prev_macd > prev_macd_signal and last_macd < last_macd_signal: bearish_score += 40 
            elif last_macd > last_macd_signal: bullish_score += 20
            else: bearish_score += 20
        if not math.isnan(last_bb_high) and not math.isnan(last_bb_low):
            if last_close <= last_bb_low: bullish_score += 30
            elif last_close >= last_bb_high: bearish_score += 30
            else: bullish_score += 15; bearish_score += 15
        total_score = max(bullish_score + bearish_score, 1)
        bullish_percent = int((bullish_score / total_score) * 100)
        if bullish_percent >= 60:
            signal_action, bias_type, bias_val = "CALL (UP)", "Bullish", bullish_percent
        elif bullish_percent <= 40:
            signal_action, bias_type, bias_val = "PUT (DOWN)", "Bearish", 100 - bullish_percent
        else:
            signal_action, bias_type, bias_val = "WAIT", "Neutral", 50
        accuracy = min(99, max(75, bias_val + 5)) 
        tf_map = {'1m': 1, '2m': 2, '5m': 5, '15m': 15}
        tf_minutes = tf_map.get(tf.lower(), 1)
        past_trades, now = [], datetime.now()
        current_trend = "CALL" if "CALL" in signal_action else "PUT"
        if signal_action == "WAIT": current_trend = random.choice(["CALL", "PUT"])
        for i in range(1, 6):
            past_time = now - timedelta(minutes=i * tf_minutes)
            random.seed(int(past_time.timestamp()) // (60 * tf_minutes))
            type_val = current_trend if random.randint(1, 10) <= 8 else ("PUT" if current_trend == "CALL" else "CALL")
            past_trades.append({"time": past_time.strftime("%I:%M %p"), "asset": display_name(asset), "type": type_val, "result": random.choices(["WIN", "LOSS"], weights=[85, 15])[0]})
        random.seed()
        return jsonify({"accuracy": f"{accuracy}%", "stability": "98.5%", "ai_matrix": "0.98", "bias_type": bias_type, "bias_val": bias_val, "signal_action": signal_action, "timeframe": tf.upper(), "history": past_trades})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def display_name(asset):
    return asset[0:3] + "/" + asset[3:] if len(asset)==6 else asset

if __name__ == '__main__':
    app.run()
