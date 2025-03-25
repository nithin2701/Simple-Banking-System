from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import random
from datetime import datetime
from functools import wraps
from itsdangerous import URLSafeTimedSerializer
import hashlib

app = Flask(__name__)
app.secret_key = '8123'  # Required for flashing messages

# Secret key for generating tokens
s = URLSafeTimedSerializer(app.secret_key)

def connect_db():
    try:
        conn = sqlite3.connect('bank.db')
        conn.row_factory = sqlite3.Row  # Enable row factory for named columns
        cursor = conn.cursor()
        
        # Create customers table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS customers (
                customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT,
                contact TEXT,
                password TEXT
            )
        ''')

        # Create accounts table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                account_id INTEGER PRIMARY KEY,
                customer_id INTEGER,
                account_type TEXT NOT NULL,
                balance REAL DEFAULT 0.0,
                FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
            )
        ''')
        
        # Create transactions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                transaction_type TEXT NOT NULL,
                amount REAL NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts (account_id)
            )
        ''')
        
        conn.commit()
        return conn, cursor
    except Exception as e:
        print(f"Database connection error: {e}")
        return None, None

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def validate_account_exists(cursor, account_id):
    #Check if an account exists in the database.
    cursor.execute('SELECT account_id FROM accounts WHERE account_id = ?', (account_id,))
    return cursor.fetchone() is not None

def generate_account_id():
    return random.randint(100000, 999999)  # Generate a 6-digit random account ID

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = hash_password(password)
        
        conn, cursor = connect_db()
        cursor.execute('SELECT a.account_id, c.name FROM customers c JOIN accounts a ON c.customer_id = a.customer_id WHERE c.name = ? AND c.password = ?', 
                    (username, hashed_password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session['username'] = user[1]
            session['account_id'] = user[0]
            flash(f'Login successful! Welcome {user[1]} (Account ID: {user[0]})', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials', 'error')
            return render_template('login.html')
    # Clear any existing flash messages on GET request
    if request.method == 'GET':
        return render_template('login.html')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def root():
    return redirect(url_for('login'))

@app.route('/index')
@login_required
def index():
    return render_template('index.html')

@app.route('/create_account', methods=['GET', 'POST'])
def create_account():
    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        contact = request.form['contact']
        account_type = request.form['account_type']
        password = request.form['password']
        hashed_password = hash_password(password)
        
        conn, cursor = connect_db()

        # Check if the user already exists
        cursor.execute('SELECT customer_id FROM customers WHERE name = ? AND contact = ?', (name, contact))
        existing_user = cursor.fetchone()
        
        if existing_user:
            flash('User already exists. Please login.', 'error')
            conn.close()
            return redirect(url_for('login'))
        
        try:
            cursor.execute('INSERT INTO customers (name, address, contact, password) VALUES (?, ?, ?, ?)', 
                        (name, address, contact, hashed_password))
            customer_id = cursor.lastrowid

            account_id = generate_account_id()  # Generate a 6-digit account ID
            cursor.execute('INSERT INTO accounts (account_id, customer_id, account_type) VALUES (?, ?, ?)', 
                        (account_id, customer_id, account_type))
            
            conn.commit()
            flash(f'Account created successfully! Your account ID: {account_id}. Please login.', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Error creating account: {str(e)}', 'error')
        finally:
            conn.close()
            
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/transaction', methods=['GET', 'POST'])
@login_required
def transaction():
    if request.method == 'POST':
        try:
            # Use the account_id from the session instead of requiring user input
            account_id = session.get('account_id')
            amount = float(request.form['amount'])
            transaction_type = request.form['transaction_type']
            
            conn, cursor = connect_db()
            
            if not validate_account_exists(cursor, account_id):
                flash('Invalid account ID', 'error')
                conn.close()
                return redirect(url_for('transaction'))
            
            if transaction_type == 'deposit':
                success, message = deposit(conn, cursor, account_id, amount)
            elif transaction_type == 'withdraw':
                success, message = withdraw(conn, cursor, account_id, amount)
            else:
                success = False
                message = 'Invalid transaction type'
                
            if success:
                flash(message, 'success')
            else:
                flash(message, 'error')
                
            conn.close()
        except ValueError:
            flash('Please enter valid numeric values', 'error')
        except Exception as e:
            flash(f'Transaction error: {str(e)}', 'error')
        return redirect(url_for('index'))
    
    # Pass the account_id to the template so it can be displayed
    account_id = session.get('account_id')
    return render_template('transaction.html', account_id=account_id)

@app.route('/balance', methods=['GET', 'POST'])
@login_required
def balance():
    # Get account_id directly from the session
    account_id = session.get('account_id')
    
    if account_id:
        try:
            conn, cursor = connect_db()
            
            if not validate_account_exists(cursor, account_id):
                flash('Invalid account ID in session', 'error')
                conn.close()
                return redirect(url_for('index'))
            
            balance = get_balance(conn, cursor, account_id)
            conn.close()
            
            message = f'Account balance: ${balance}'
            return render_template('balance.html', message=message, account_id=account_id)
        except Exception as e:
            flash(f'Error retrieving balance: {str(e)}', 'error')
            return redirect(url_for('index'))
    else:
        flash('No account ID found in session', 'error')
        return redirect(url_for('login'))

def get_balance(conn, cursor, account_id):
    cursor.execute('SELECT balance FROM accounts WHERE account_id = ?', (account_id,))
    result = cursor.fetchone()
    return result[0] if result else 0.0

@app.route('/history', methods=['GET', 'POST'])
@login_required
def history():
    # Get account_id directly from the session
    account_id = session.get('account_id')
    
    if account_id:
        try:
            conn, cursor = connect_db()
            
            if not validate_account_exists(cursor, account_id):
                flash('Invalid account ID in session', 'error')
                conn.close()
                return redirect(url_for('index'))
            
            transactions = get_history(conn, cursor, account_id)
            conn.close()
            
            return render_template('history.html', transactions=transactions, account_id=account_id)
        except Exception as e:
            flash(f'Error retrieving transaction history: {str(e)}', 'error')
            return redirect(url_for('index'))
    else:
        flash('No account ID found in session', 'error')
        return redirect(url_for('login'))

def get_history(conn, cursor, account_id):
    cursor.execute('''
        SELECT transaction_type, amount, timestamp 
        FROM transactions 
        WHERE account_id = ? 
        ORDER BY timestamp DESC
    ''', (account_id,))
    return cursor.fetchall()

def deposit(conn, cursor, account_id, amount):
    if amount <= 0:
        return False, 'Deposit amount must be positive'
    try:
        cursor.execute('UPDATE accounts SET balance = balance + ? WHERE account_id = ?', (amount, account_id))
        cursor.execute('INSERT INTO transactions (account_id, transaction_type, amount) VALUES (?, ?, ?)',
                      (account_id, 'deposit', amount))
        conn.commit()
        return True, f'Successfully deposited ${amount}'
    except Exception as e:
        conn.rollback()
        return False, f'Deposit failed: {str(e)}'

def withdraw(conn, cursor, account_id, amount):
    if amount <= 0:
        return False, 'Withdrawal amount must be positive'
    try:
        cursor.execute('SELECT balance FROM accounts WHERE account_id = ?', (account_id,))
        current_balance = cursor.fetchone()[0]
        if current_balance >= amount:
            cursor.execute('UPDATE accounts SET balance = balance - ? WHERE account_id = ?', (amount, account_id))
            cursor.execute('INSERT INTO transactions (account_id, transaction_type, amount) VALUES (?, ?, ?)',
                          (account_id, 'withdraw', amount))
            conn.commit()
            return True, f'Successfully withdrew ${amount}'
        return False, 'Insufficient funds'
    except Exception as e:
        conn.rollback()
        return False, f'Withdrawal failed: {str(e)}'

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('account_id', None) 
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username')
        account_id = request.form.get('account_id')
        conn, cursor = connect_db()
        cursor.execute('SELECT account_id FROM accounts WHERE account_id = ? AND customer_id = (SELECT customer_id FROM customers WHERE name = ?)', 
                      (account_id, username))
        user = cursor.fetchone()
        conn.close()
        if user:
            token = s.dumps(account_id, salt='password-reset-salt')
            reset_url = url_for('reset_password', token=token, _external=True)
            flash(f'Use this link to reset your password: <a href="{reset_url}">{reset_url}</a>', 'link')
        else:
            flash('Username or Account ID not found', 'error')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        account_id = s.loads(token, salt='password-reset-salt', max_age=3600)
    except:
        flash('The password reset link is invalid or has expired.', 'error')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        new_password = request.form.get('password')
        hashed_password = hash_password(new_password)
        
        conn, cursor = connect_db()
        cursor.execute('SELECT customer_id FROM accounts WHERE account_id = ?', (account_id,))
        customer_id = cursor.fetchone()
        
        if customer_id:
            cursor.execute('UPDATE customers SET password = ? WHERE customer_id = ?', 
                          (hashed_password, customer_id[0]))
            conn.commit()
            flash('Your password has been updated.', 'success')
        else:
            flash('Account not found.', 'error')
        
        conn.close()
        return redirect(url_for('login'))
    
    return render_template('reset_password.html')

if __name__ == '__main__':
    app.run(debug=True)