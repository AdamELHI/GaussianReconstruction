#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

sudo apt-get update
sudo apt-get install -y \
  build-essential \
  cmake \
  curl \
  git \
  pkg-config \
  libssl-dev \
  libudev-dev \
  libclang-dev \
  clang \
  python3-pip \
  python3-venv

sudo apt-get install -y colmap

if [ ! -d "$HOME/.cargo" ]; then
  curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal --default-toolchain stable
fi

export PATH="$HOME/.cargo/bin:$PATH"
source "$HOME/.cargo/env" 2>/dev/null || true
rustup default stable
rustup update stable

cd /home/ubuntu/Stage/Test_env
if [ ! -d brush ]; then
  git clone https://github.com/ArthurBrussee/brush.git brush
fi

cd brush
cargo --version
cargo check --workspace --quiet
