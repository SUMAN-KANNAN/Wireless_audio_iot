from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta

app = Flask(__name__)
app.secret_key = 'maud82hd92m!@f8dsJDFN3209dfnv@#3j'
app.permanent_session_lifetime = timedelta(minutes=30)

# Dummy credentials
USER_CREDENTIALS = {
    'admin': 'password',
    'user': '123'
}

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Authentication check
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session.permanent = True
            session['user'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid username or password")

    return render_template('login.html', error=None)

@app.route('/dashboard')
def dashboard():
    if 'user' in session:
        return render_template('landing.html', user=session['user'])  # <-- render landing.html here
    else:
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
