#!/bin/bash
echo "Setting up Enterprise Text-to-SQL Pipeline..."

# Check if python3.12 is installed
if command -v python3.12 &> /dev/null; then
    echo "Python 3.12 found! Creating virtual environment..."
    python3.12 -m venv venv
else
    echo "=========================================================="
    echo "CRITICAL ERROR: Python 3.12 is required but not found!"
    echo "Your default Python version is too new or too old."
    echo "Please install Python 3.12 to continue."
    echo "  - Mac: brew install python@3.12"
    echo "  - Ubuntu: sudo apt install python3.12 python3.12-venv"
    echo "  - Windows: Download from python.org"
    echo "=========================================================="
    exit 1
fi

echo "Activating virtual environment and installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt

echo "Setup Complete! You can now run the application."
