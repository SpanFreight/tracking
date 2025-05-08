#!/bin/bash
echo "Installing dependencies with proper order for binary compatibility..."
pip install --upgrade pip
pip install numpy==1.25.2
pip install -r requirements.txt
echo "Dependencies installed successfully!"
