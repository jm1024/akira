#!/bin/bash

set -e

echo "========================================="
echo "Installing OpenAI Codex CLI"
echo "========================================="

##############
# install dependencies

sudo apt update
sudo apt install -y \
    curl \
    ca-certificates \
    git \
    build-essential

##############
# install nodejs 22 lts

if command -v node >/dev/null 2>&1; then
    echo "Node already installed:"
    node --version
else
    echo "Installing Node.js 22 LTS..."

    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -

    sudo apt install -y nodejs
fi

##############
# verify node/npm

echo "Node version:"
node --version

echo "NPM version:"
npm --version

##############
# install codex cli

echo "Installing Codex CLI..."

sudo npm install -g @openai/codex

##############
# verify codex

echo "Codex version:"
codex --version

echo
echo "========================================="
echo "Codex CLI installed successfully"
echo "========================================="
echo
echo "Next steps:"
echo
echo "1. Authenticate:"
echo "   codex auth"
echo
echo "2. Start Codex inside a project:"
echo "   cd /path/to/project"
echo "   codex"
echo
