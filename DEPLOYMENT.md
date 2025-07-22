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

### Step 5: Run the App with Gunicorn

The Flask development server (`python app.py`) is not for production. We will use Gunicorn, a robust WSGI server.

1.  **Run the Gunicorn Command:**
    The `geventwebsocket` worker is crucial for handling the WebSocket connections. To keep the server running after you close your SSH session, run it with `nohup`:
    ```bash
    nohup gunicorn --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 --bind 0.0.0.0:5000 app:app &
    ```
    - The `&` at the end runs the process in the background. You can now safely close your SSH terminal.

---

### Step 6: Final Configuration

1.  **Update ESP32 Firmware:**
    - Open your `firmware.ino` file on your local computer.
    - Change the `websocket_server_address` to the **Public IPv4 address** of your EC2 instance.
    - Re-upload the firmware to your ESP32 device(s).

2.  **Access Your Dashboard:**
    - Open a web browser and navigate to `http://your-public-ip-address:5000`