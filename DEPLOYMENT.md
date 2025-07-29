# Production Deployment Guide (AWS EC2)

This guide provides step-by-step instructions for deploying the Python Flask server to an AWS EC2 instance, making it accessible over the internet.

## Prerequisites

- An AWS account.
- Git installed on your local machine.
- An SSH client. On Windows, you can use PowerShell or Git Bash. On macOS/Linux, the `ssh` command is built-in.

---

### Step 1: Launch an AWS EC2 Instance

1.  **Log in to the AWS Management Console** and navigate to the EC2 dashboard.
2.  Click **"Launch instance"**.
3.  **Name and tags:** Give your server a recognizable name, e.g., `WirelessAudioServer`.
4.  **Application and OS Images (AMI):** Search for and select **Ubuntu**. Choose the latest LTS version (e.g., Ubuntu Server 22.04 LTS).
5.  **Instance type:** Select **`t2.micro`**. This is eligible for the AWS Free Tier.
6.  **Key pair (for login):**
    - Click **"Create new key pair"**.
    - **Key pair name:** Enter a name, e.g., `audio-server-key`.
    - **Key pair type:** RSA
    - **Private key file format:** `.pem`
    - Click **"Create key pair"**. Your browser will download the `.pem` file. **Store this file securely; you cannot download it again.**
7.  **Network settings (Security Group):**
    - This is the most important step for connectivity. Click **"Edit"**.
    - Under "Security group rule 1", the SSH rule for your IP should already be there.
    - Click **"Add security group rule"** two more times to add the following:
        - **Rule 2:**
            - **Type:** `Custom TCP`
            - **Port range:** `5000` (This is our application port)
            - **Source type:** `Anywhere` (0.0.0.0/0)
        - **Rule 3:**
            - **Type:** `HTTP`
            - **Port range:** `80`
            - **Source type:** `Anywhere` (0.0.0.0/0)
8.  **Configure storage:** The default 8 GB is sufficient.
9.  Review the summary and click **"Launch instance"**.

---

### Step 2: Connect to Your EC2 Instance

1.  Go back to the EC2 dashboard, find your newly created instance, and wait for the "Instance state" to become "Running".
2.  Select the instance and copy its **Public IPv4 address**.
3.  Open a terminal on your local machine, navigate to the directory where you saved your `.pem` file, and run the following command (replace the placeholders):

    ```bash
    # First, make your key file read-only
    chmod 400 your-key-name.pem

    # Then, connect via SSH
    ssh -i "your-key-name.pem" ubuntu@your-public-ip-address
    ```
    - Type `yes` when prompted to continue connecting. You are now logged into your server.

---

### Step 3: Set Up the Server Environment

Run these commands on the EC2 instance via your SSH connection.

1.  **Update System Packages:**
    ```bash
    sudo apt update
    sudo apt upgrade -y
    ```
2.  **Install Python, Pip, and Git:**
    ```bash
    sudo apt install python3-pip python3-venv git -y
    ```
3.  **Install and Run Redis (for State Management):**
    Redis is used for robust, high-performance state management, replacing the local JSON files.
    ```bash
    sudo apt install redis-server -y
    sudo systemctl enable redis-server.service # Ensures Redis starts on boot
    ```

---

### Step 4: Deploy the Application

1.  **Clone Your Project:**
    ```bash
    git clone https://github.com/SUMAN-KANNAN/Wireless_audio_iot.git
    cd Wireless_audio_iot
    ```
2.  **Set Up Python Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```
3.  **Set Environment Variables (Recommended):**
    For better security, set your secret keys as environment variables.
    ```bash
    export SECRET_KEY='a-very-strong-and-random-secret-key'
    export DEVICE_API_KEY='a-different-super-secret-key'
    ```
    *Note: These variables only last for your current session. For a permanent solution, add them to your `~/.bashrc` file.*

---

### Step 5: Run the App as a Systemd Service (Production Method)

The Flask development server is not for production. Using `nohup` is better, but the professional way to run a long-term application on Linux is with `systemd`. This ensures your app starts on boot and restarts automatically if it crashes.

1.  **Create the Service File:**
    First, you need to create a service file for `systemd`. A template for this file is included in the repository at `deployment/wireless-audio.service`. You will create and edit this file on your server.
    ```bash
    sudo nano /etc/systemd/system/wireless-audio.service
    ```
    Paste the following content into the editor. **Important:** If you used different secret keys in the previous step, update the `Environment` lines here to match.

    ```ini
    [Unit]
    Description=Gunicorn instance to serve the Wireless Audio System
    After=network.target redis-server.service
    
    [Service]
    User=ubuntu
    WorkingDirectory=/home/ubuntu/Wireless_audio_iot
    Environment="SECRET_KEY=a-very-strong-and-random-secret-key"
    Environment="DEVICE_API_KEY=a-different-super-secret-key"
    # Set to "False" in production to keep room states (like volume) after a server restart
    Environment="CLEAR_REDIS_ON_STARTUP=False"
    ExecStart=/home/ubuntu/Wireless_audio_iot/venv/bin/gunicorn --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 --bind 0.0.0.0:5000 app:app
    Restart=always
    
    [Install]
    WantedBy=multi-user.target
    ```
    
    - Press `Ctrl+X`, then `Y`, then `Enter` to save and exit `nano`.

2.  **Start and Enable the Service:**
    Now, tell `systemd` to start your service and enable it to launch automatically on boot.
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start wireless-audio
    sudo systemctl enable wireless-audio
    ```

3.  **Check the Status:**
    You can verify that the service is running correctly:
    ```bash
    sudo systemctl status wireless-audio
    ```
    - Press `q` to exit the status view. You can now safely close your SSH connection, and the server will keep running.

---

### Step 6: Set Up Nginx as a Reverse Proxy (Crucial for Production)

Exposing the Gunicorn server directly is not secure. Nginx will act as a production-grade web server that handles internet traffic and forwards it to your application. This also allows you to easily add SSL/TLS (HTTPS) encryption.

1.  **Install Nginx:**
    ```bash
    sudo apt install nginx -y
    ```

2.  **Create an Nginx Configuration File:**
    ```bash
    sudo nano /etc/nginx/sites-available/wireless-audio
    ```
    Paste the following configuration. This tells Nginx to listen on port 80 and proxy requests to your Gunicorn app. It also includes headers needed for WebSockets to work correctly.

    ```nginx
    server {
        listen 80;
        server_name your-public-ip-address; # Replace with your EC2's Public IP

        location / {
            proxy_pass http://127.0.0.1:5000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /ws/ {
            proxy_pass http://127.0.0.1:5000/ws/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "Upgrade";
            proxy_set_header Host $host;
        }
    }
    ```

3.  **Enable the Configuration:**
    Link the file to the `sites-enabled` directory to activate it.
    ```bash
    sudo ln -s /etc/nginx/sites-available/wireless-audio /etc/nginx/sites-enabled
    sudo nginx -t # Test the configuration for syntax errors
    sudo systemctl restart nginx
    ```

---

### Step 7: Secure Your Server with SSL (HTTPS) - Recommended

Using HTTPS is **critical** for any production website, especially one that requests microphone access. This step uses **Certbot** to automatically get a free SSL certificate from Let's Encrypt and configure Nginx.

1.  **Prerequisite: A Domain Name**
    - You cannot get an SSL certificate for a raw IP address. You must have a domain name (e.g., `your-domain.com`) pointing to your EC2 instance's Public IPv4 address. You can get a domain from providers like Namecheap, GoDaddy, etc.
    - In your domain provider's DNS settings, create an **"A" record** where the **Host** is `@` (or your domain name) and the **Value** is your EC2's public IP.

2.  **Install Certbot:**
    ```bash
    sudo apt install certbot python3-certbot-nginx -y
    ```

3.  **Run Certbot:**
    Replace `your-domain.com` with your actual domain name. Certbot will automatically edit your Nginx configuration file (`/etc/nginx/sites-available/wireless-audio`) to add SSL settings and handle certificate renewal.
    ```bash
    sudo certbot --nginx -d your-domain.com
    ```
    - Follow the on-screen prompts. When asked about redirecting HTTP traffic to HTTPS, it is highly recommended to choose the redirect option.

4.  **Verify Auto-Renewal:**
    Certbot sets up a scheduled task to renew your certificate automatically. You can test it with:
    ```bash
    sudo certbot renew --dry-run
    ```

---

### Step 8: Final Configuration

1.  **Update ESP32 Firmware:**
    - Open your `firmware.ino` file on your local computer.
    - **Important:** The mDNS discovery will not work over the internet. You must comment out the `discoverAudioServer()` call in `setup()` and manually set the `server_address` to the **Public IPv4 address** of your EC2 instance.
    - Re-upload the firmware to your ESP32 device(s). *Note: For a production HTTPS setup, you would need to use a WebSocket library on the ESP32 that supports secure connections (`wss://`). This often requires more memory.*
    -   **Set Production Mode:** In `firmware.ino`, change the `PRODUCTION` macro from `0` to `1`. This enables the physical battery sensor instead of the simulated battery drain.
      ```cpp
      // Set to 1 for real-world deployment (uses physical battery sensor).
      #define PRODUCTION 1
      ```

2.  **Access Your Dashboard:**
    - You can now access your dashboard securely through Nginx. Open a web browser and navigate to:
      `http://your-public-ip-address` (no port number needed).