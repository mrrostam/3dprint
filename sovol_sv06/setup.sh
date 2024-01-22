#!/bin/bash

ACTION=$1
TARGET_DIR="/home/dynamix/printer_data/config"
PACKAGE="klipper"

case "$ACTION" in
  install)
    stow --target="$TARGET_DIR" "$PACKAGE"
    ;;
  uninstall)
    stow -D --target="$TARGET_DIR" "$PACKAGE"
    ;;
  *)
    echo "Usage: $0 {install|uninstall}"
    exit 1
    ;;
esac
