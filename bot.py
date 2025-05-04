#!/usr/bin/env python
# coding: utf-8

import time
import math
import logging
from datetime import datetime
import pandas as pd
import os
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
from binance.enums import *

# ---------------------------
# CONFIGURACIÓN INICIAL
# ---------------------------

# Configuración del registro de errores y eventos
logging.basicConfig(filename='trading_bot.log', 
                    level=logging.DEBUG, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Load API credentials from config.json
import json
with open('config.json') as config_file:
    config = json.load(config_file)

# Configuración de la API de Binance
API_KEY = config['API_KEY']
API_SECRET = config['API_SECRET']
client = Client(API_KEY, API_SECRET)

# Configuración del bot
SYMBOL = 'DOGEUSDT'         # Par de trading
INTERVAL = '1m'             # Intervalo para obtener datos (scalping)
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
STOP_LOSS_PERCENT = 0.01    # 1%
TAKE_PROFIT_PERCENT = 0.02  # 2%
RESERVED_USDT = 20.0        # Reserva mínima en USDT para comisiones

# Archivo para registrar operaciones
TRADES_FILE = 'trades_log.xlsx'
if not os.path.exists(TRADES_FILE):
    df_trades = pd.DataFrame(columns=['Timestamp', 'Symbol', 'Side', 'Quantity', 'Entry Price', 
                                        'Stop Loss', 'Take Profit', 'Exit Price', 'Result'])
    df_trades.to_excel(TRADES_FILE, index=False)

# ---------------------------
# FUNCIONES AUXILIARES
# ---------------------------

def get_balance(asset='USDT'):
    """Obtiene el balance libre para el activo indicado."""
    try:
        account_info = client.get_account()
        for balance in account_info['balances']:
            if balance['asset'] == asset:
                free_balance = float(balance['free'])
                locked_balance = float(balance['locked'])
                logging.debug(f"Saldo {asset} - Libre: {free_balance}, Bloqueado: {locked_balance}")
                return free_balance
        return 0.0
    except Exception as e:
        logging.error(f"Error al obtener balance de {asset}: {e}")
        return 0.0

def calculate_rsi(series, period):
    """Calcula el RSI a partir de una serie de precios."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def get_indicators():
    """
    Obtiene las últimas 100 velas y calcula los indicadores: 
    EMA rápida, EMA lenta y RSI.
    """
    try:
        klines = client.get_klines(symbol=SYMBOL, interval=INTERVAL, limit=100)
        df = pd.DataFrame(klines, columns=['open_time', 'open', 'high', 'low', 'close', 'volume',
                                             'close_time', 'quote_asset_volume', 'number_of_trades', 
                                             'taker_buy_base', 'taker_buy_quote', 'ignore'])
        df['close'] = df['close'].astype(float)
        df['ema_fast'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
        df['rsi'] = calculate_rsi(df['close'], RSI_PERIOD)
        return df
    except Exception as e:
        logging.error(f"Error al obtener indicadores: {e}")
        raise

def adjust_quantity(quantity, step_size):
    """Ajusta la cantidad según el step_size permitido por el mercado."""
    return math.floor(quantity / step_size) * step_size

def calculate_quantity(price):
    """
    Calcula la cantidad de DOGE a comprar con el balance USDT disponible,
    respetando las restricciones del mercado.
    """
    try:
        usdt_balance = get_balance('USDT')
        logging.debug(f"Balance USDT disponible: {usdt_balance}")
        if usdt_balance <= RESERVED_USDT:
            logging.error("Saldo insuficiente después de reservar USDT para comisiones.")
            return 0.0
        adjusted_balance = usdt_balance - RESERVED_USDT

        # Obtener restricciones del símbolo
        info = client.get_symbol_info(SYMBOL)
        filters = info['filters']
        min_qty = None
        step_size = None
        min_notional = None
        for f in filters:
            if f['filterType'] == 'LOT_SIZE':
                min_qty = float(f['minQty'])
                step_size = float(f['stepSize'])
            if f['filterType'] == 'NOTIONAL':
                min_notional = float(f['minNotional'])

        if step_size is None:
            logging.error("No se pudo obtener la restricción 'step_size' del símbolo.")
            return 0.0

        max_qty = adjusted_balance / price
        quantity = adjust_quantity(max_qty, step_size)
        trade_value = quantity * price

        if quantity < min_qty or trade_value < min_notional:
            logging.error(f"Cantidad o valor insuficiente para cumplir restricciones: Cantidad {quantity}, Valor {trade_value}")
            return 0.0

        logging.debug(f"Cantidad calculada para comprar: {quantity}")
        return round(quantity, 6)
    except Exception as e:
        logging.error(f"Error al calcular cantidad: {e}")
        return 0.0

def execute_market_order(side, quantity):
    """
    Ejecuta una orden de mercado y retorna la respuesta de Binance.
    """
    try:
        order = client.create_order(symbol=SYMBOL, side=side, type=ORDER_TYPE_MARKET, quantity=quantity)
        logging.info(f"Orden ejecutada: {side}, Cantidad: {quantity}. Orden: {order}")
        return order
    except BinanceAPIException as e:
        logging.error(f"Error en orden de mercado: {e}")
        return None
    except BinanceOrderException as e:
        logging.error(f"Error en la orden: {e}")
        return None

def log_trade(trade):
    """
    Registra la operación en el archivo de trades. 
    Se espera que 'trade' sea un diccionario con los datos a guardar.
    """
    try:
        df = pd.read_excel(TRADES_FILE)
        df = df.append(trade, ignore_index=True)
        df.to_excel(TRADES_FILE, index=False)
        logging.info("Operación registrada en archivo de trades.")
    except Exception as e:
        logging.error(f"Error al registrar la operación: {e}")

# ---------------------------
# FUNCIONES DE OPERATIVA
# ---------------------------

def monitor_trade(entry_price, quantity):
    """
    Monitorea la posición abierta (long) y cierra la posición (vender DOGE) 
    cuando se cumpla el stop loss o take profit.
    Retorna: (order, resultado, precio de salida)
    """
    try:
        current_price = float(client.get_symbol_ticker(symbol=SYMBOL)['price'])
        stop_loss_price = entry_price * (1 - STOP_LOSS_PERCENT)
        take_profit_price = entry_price * (1 + TAKE_PROFIT_PERCENT)
        logging.info(f"Monitoreando posición. Precio actual: {current_price}, "
                     f"Stop Loss: {stop_loss_price}, Take Profit: {take_profit_price}")

        if current_price <= stop_loss_price:
            logging.info("Se cumple condición de STOP LOSS. Ejecutando venta...")
            order = execute_market_order(SIDE_SELL, quantity)
            return order, "Stop Loss", current_price

        elif current_price >= take_profit_price:
            logging.info("Se cumple condición de TAKE PROFIT. Ejecutando venta...")
            order = execute_market_order(SIDE_SELL, quantity)
            return order, "Take Profit", current_price

        return None, "Abierta", current_price

    except Exception as e:
        logging.error(f"Error en el monitoreo de la operación: {e}")
        return None, "Error", None

def run_bot():
    """
    Función principal del bot.  
    - Si no hay posición abierta, evalúa los indicadores y si se cumplen las condiciones de entrada, compra DOGE.  
    - Si hay posición abierta, la monitorea y la cierra al cumplirse stop loss o take profit.
    """
    position_open = False
    entry_price = 0.0
    quantity = 0.0

    while True:
        try:
            df = get_indicators()
            last_row = df.iloc[-1]
            ema_fast = last_row['ema_fast']
            ema_slow = last_row['ema_slow']
            rsi = last_row['rsi']
            close_price = last_row['close']
            logging.debug(f"Indicadores - EMA rápida: {ema_fast}, EMA lenta: {ema_slow}, RSI: {rsi}, Precio: {close_price}")

            if not position_open:
                # Condición de entrada: por ejemplo, EMA rápida > EMA lenta y RSI entre 30 y 70
                if ema_fast > ema_slow and 30 < rsi < 70:
                    quantity = calculate_quantity(close_price)
                    if quantity > 0:
                        order = execute_market_order(SIDE_BUY, quantity)
                        if order is not None:
                            entry_price = close_price
                            position_open = True
                            logging.info(f"Posición abierta (BUY) a {entry_price} con cantidad {quantity}")
                            # Registrar operación de entrada
                            trade_entry = {
                                'Timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                'Symbol': SYMBOL,
                                'Side': 'BUY',
                                'Quantity': quantity,
                                'Entry Price': entry_price,
                                'Stop Loss': entry_price * (1 - STOP_LOSS_PERCENT),
                                'Take Profit': entry_price * (1 + TAKE_PROFIT_PERCENT),
                                'Exit Price': None,
                                'Result': None
                            }
                            log_trade(trade_entry)
                        else:
                            logging.error("Error al ejecutar orden de compra.")
            else:
                # Monitorear posición abierta y, si se cumplen las condiciones, cerrar la operación (vender)
                order, result, exit_price = monitor_trade(entry_price, quantity)
                if result in ["Stop Loss", "Take Profit"]:
                    if order is not None:
                        logging.info(f"Posición cerrada ({result}) a {exit_price}")
                        # Registrar la salida de la operación
                        trade_exit = {
                            'Timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            'Symbol': SYMBOL,
                            'Side': 'SELL',
                            'Quantity': quantity,
                            'Entry Price': entry_price,
                            'Stop Loss': entry_price * (1 - STOP_LOSS_PERCENT),
                            'Take Profit': entry_price * (1 + TAKE_PROFIT_PERCENT),
                            'Exit Price': exit_price,
                            'Result': result
                        }
                        log_trade(trade_exit)
                    # Reiniciar variables para buscar nueva oportunidad
                    position_open = False
                    entry_price = 0.0
                    quantity = 0.0

            time.sleep(10)  # Espera 10 segundos antes de la siguiente verificación

        except Exception as e:
            logging.error(f"Error en el loop principal: {e}")
            time.sleep(10)

# ---------------------------
# EJECUCIÓN DEL BOT
# ---------------------------

if __name__ == "__main__":
    run_bot()

